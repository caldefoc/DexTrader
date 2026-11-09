#!/bin/bash
# tree-manual.sh - Fully reliable tree with pruning

PRUNE_DIRS=('node_modules' '.next' 'dist' 'build' 'coverage' '.git' '.vscode')

print_tree() {
  local dir="$1"
  local prefix="$2"
  local depth="$3"
  
  [[ $depth -gt 15 ]] && return  # Safety limit
  
  local items=()
  while IFS= read -r item; do
    items+=("$item")
  done < <(ls -1A "$dir" 2>/dev/null | sort)
  
  local total=${#items[@]}
  local i=0
  
  for item in "${items[@]}"; do
    ((i++))
    local path="${dir}/${item}"
    local connector=$([[ $i -eq $total ]] && echo "└── " || echo "├── ")
    
    echo "${prefix}${connector}${item}"
    
    if [[ -d "$path" ]]; then
      # Check if this directory should be pruned
      local should_prune=0
      for prune_dir in "${PRUNE_DIRS[@]}"; do
        [[ "$item" == "$prune_dir" ]] && { should_prune=1; break; }
      done
      
      if [[ $should_prune -eq 0 ]]; then
        local new_prefix="${prefix}$([[ $i -eq $total ]] && echo "    " || echo "│   ")"
        print_tree "$path" "$new_prefix" $((depth + 1))
      fi
    fi
  done
}

echo "$(basename "$(pwd)")/"
print_tree "." "" 0
