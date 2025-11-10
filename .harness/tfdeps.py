#!/usr/bin/env python3
"""
tfdeps - Terraform Module Dependency Analyzer

Analyzes Terraform module dependencies including explicit module references
and implicit dependencies through data source naming patterns.
Now includes ALL modules in output, regardless of dependencies.
"""

import os
import re
import sys
import argparse
from collections import defaultdict


class TFDeps:
    """Main class for analyzing Terraform module dependencies."""
    
    def __init__(self, verbose=False):
        self.verbose = verbose
        self.modules_dir = None
        self.dependencies = defaultdict(set)
        self.provider_aliases = defaultdict(set)
        self.all_modules = set()  # Track ALL modules found
        
    def log(self, message):
        """Print verbose messages if enabled."""
        if self.verbose:
            print(f"[VERBOSE] {message}")
    
    def remove_comments(self, content):
        """Remove all comments from Terraform content."""
        # Remove block comments /* ... */
        content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
        # Remove single-line comments // and #
        content = re.sub(r'//.*?$', '', content, flags=re.MULTILINE)
        content = re.sub(r'#.*?$', '', content, flags=re.MULTILINE)
        return content
    
    def extract_modules_dir(self, hcl_file):
        """Extract modules_dir from HCL file block comment."""
        try:
            with open(hcl_file, 'r') as f:
                content = f.read()
        except IOError as e:
            print(f"Error reading HCL file: {e}")
            return None
            
        # Look for modules_dir in block comments
        pattern = r'/\*.*modules_dir:\s*([^\s*]+).*?\*/'
        match = re.search(pattern, content, re.DOTALL)
        
        if match:
            path = match.group(1).strip()
            # Handle both relative and absolute paths
            if not os.path.isabs(path):
                base_dir = os.path.dirname(os.path.abspath(hcl_file))
                path = os.path.join(base_dir, path)
            return os.path.normpath(path)
        
        print("Error: No modules_dir configuration found in HCL file")
        return None
    
    def scan_modules(self):
        """Scan modules directory for ALL subdirectories."""
        if not self.modules_dir or not os.path.isdir(self.modules_dir):
            print(f"Error: Invalid modules directory: {self.modules_dir}")
            return []
        
        self.log(f"Scanning modules directory: {self.modules_dir}")
        
        modules = []
        try:
            items = os.listdir(self.modules_dir)
            self.log(f"Found {len(items)} items in directory")
            
            for item in sorted(items):
                item_path = os.path.join(self.modules_dir, item)
                if os.path.isdir(item_path) and not item.startswith('.'):
                    modules.append(item)
                    self.log(f"Found module: {item}")
                    self.all_modules.add(item)  # Track ALL modules
                elif os.path.isfile(item_path):
                    self.log(f"Skipping file (not a module): {item}")
                elif item.startswith('.'):
                    self.log(f"Skipping hidden item: {item}")
                    
        except OSError as e:
            print(f"Error scanning modules directory: {e}")
            return []
        
        self.log(f"Total modules detected: {len(modules)}")
        return sorted(modules)
    
    def extract_provider_aliases(self, module_path):
        """Extract provider aliases from provider.tf or versions.tf files."""
        aliases = set()
        
        for filename in ['provider.tf', 'versions.tf']:
            file_path = os.path.join(module_path, filename)
            if not os.path.isfile(file_path):
                continue
                
            try:
                with open(file_path, 'r') as f:
                    content = f.read()
                content = self.remove_comments(content)
                
                # Find alias patterns
                alias_matches = re.findall(r'alias\s*=\s*"([^"]+)"', content)
                aliases.update(alias_matches)
                
                self.log(f"Found aliases in {filename}: {alias_matches}")
                
            except IOError as e:
                self.log(f"Error reading {filename}: {e}")
                continue
        
        return aliases
    
    def extract_explicit_dependencies(self, module_path):
        """Extract explicit module dependencies from module blocks."""
        dependencies = set()
        
        # Look for all .tf files
        try:
            tf_files = [f for f in os.listdir(module_path) if f.endswith('.tf')]
        except OSError:
            return dependencies
        
        for tf_file in tf_files:
            file_path = os.path.join(module_path, tf_file)
            try:
                with open(file_path, 'r') as f:
                    content = f.read()
                content = self.remove_comments(content)
                
                # Find module blocks
                module_blocks = re.findall(r'module\s+"([^"]+)"\s*\{', content)
                dependencies.update(module_blocks)
                
                if module_blocks:
                    self.log(f"Found explicit dependencies in {tf_file}: {module_blocks}")
                    
            except IOError as e:
                self.log(f"Error reading {tf_file}: {e}")
                continue
        
        return dependencies
    
    def extract_implicit_dependencies(self, module_path):
        """Extract implicit dependencies from data sources."""
        dependencies = set()
        
        # Look for all .tf files
        try:
            tf_files = [f for f in os.listdir(module_path) if f.endswith('.tf')]
        except OSError:
            return dependencies
        
        for tf_file in tf_files:
            file_path = os.path.join(module_path, tf_file)
            try:
                with open(file_path, 'r') as f:
                    content = f.read()
                content = self.remove_comments(content)
                
                # Find data source blocks
                data_blocks = re.findall(r'data\s+"[^"]+"\s+"([^"]+)"\s*\{', content)
                
                for data_name in data_blocks:
                    module_name = None
                    
                    # Check for VPC patterns
                    if '_vpc' in data_name:
                        if 'inner' in data_name:
                            module_name = 'inner_vpc'
                        elif 'outer' in data_name:
                            module_name = 'outer_vpc'
                        else:
                            # Extract prefix before _vpc
                            prefix = data_name.split('_vpc')[0]
                            if prefix:
                                module_name = f"{prefix}_vpc"
                    
                    # Check for inner/outer patterns
                    elif 'inner' in data_name:
                        module_name = 'inner_vpc'
                    elif 'outer' in data_name:
                        module_name = 'outer_vpc'
                    
                    if module_name:
                        dependencies.add(module_name)
                        self.log(f"Found implicit dependency: {data_name} -> {module_name}")
                        
            except IOError as e:
                self.log(f"Error reading {tf_file}: {e}")
                continue
        
        return dependencies
    
    def analyze_module(self, module_name):
        """Analyze a single module for dependencies and provider aliases."""
        module_path = os.path.join(self.modules_dir, module_name)
        
        self.log(f"Processing module: {module_name}")
        
        # Extract provider aliases
        aliases = self.extract_provider_aliases(module_path)
        for alias in aliases:
            self.provider_aliases[alias].add(module_name)
        
        # Extract dependencies
        explicit_deps = self.extract_explicit_dependencies(module_path)
        implicit_deps = self.extract_implicit_dependencies(module_path)
        all_deps = explicit_deps.union(implicit_deps)
        
        # Remove self-references
        all_deps.discard(module_name)
        
        for dep in all_deps:
            self.dependencies[module_name].add(dep)
        
        self.log(f"Dependencies for {module_name}: {sorted(all_deps)}")
    
    def generate_output(self, hcl_file):
        """Generate dependencies.txt output file including ALL modules."""
        output_lines = ["/*"]
        output_lines.append("MODULES:")
        
        # Include ALL modules found, not just those with dependencies
        for module in sorted(self.all_modules):
            deps = sorted(self.dependencies.get(module, []))
            if deps:
                output_lines.append(f"- {module} (depends_on: {', '.join(deps)})")
            else:
                output_lines.append(f"- {module}")
        
        # Add provider aliases
        for alias in sorted(self.provider_aliases.keys()):
            output_lines.append(f"")
            output_lines.append(f"PROVIDER {alias}:")
            for module in sorted(self.provider_aliases[alias]):
                output_lines.append(f"- {module}")
        
        output_lines.append("*/")
        
        # Write to file
        output_file = os.path.join(os.path.dirname(os.path.abspath(hcl_file)), 'dependencies.txt')
        try:
            with open(output_file, 'w') as f:
                f.write('\n'.join(output_lines))
            print(f"Successfully generated {output_file}")
        except IOError as e:
            print(f"Error writing output file: {e}")
    
    def run(self, hcl_file):
        """Main execution method."""
        # Extract modules directory
        self.modules_dir = self.extract_modules_dir(hcl_file)
        if not self.modules_dir:
            return 1
        
        # Scan for modules
        modules = self.scan_modules()
        if not modules:
            print("No modules found to analyze")
            return 1
        
        # Analyze each module
        for module in modules:
            self.analyze_module(module)
        
        # Generate output - now includes ALL modules
        self.generate_output(hcl_file)
        return 0


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Analyze Terraform module dependencies',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  tfdeps project.hcl
  tfdeps -v project.hcl
  tfdeps --verbose project.hcl
        """
    )
    
    parser.add_argument('hcl_file', help='HCL configuration file')
    parser.add_argument('-v', '--verbose', action='store_true',
                       help='Enable verbose output for debugging')
    
    args = parser.parse_args()
    
    if not os.path.isfile(args.hcl_file):
        print(f"Error: HCL file not found: {args.hcl_file}")
        return 1
    
    analyzer = TFDeps(verbose=args.verbose)
    return analyzer.run(args.hcl_file)


if __name__ == '__main__':
    sys.exit(main())
