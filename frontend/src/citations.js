// Turn source references into links without changing code blocks or existing links
export function remarkCitations({ ids }) {
  const allowed = new Set(ids)
  return tree => {
    function walk(node) {
      if (!node.children || ['link', 'code', 'inlineCode'].includes(node.type)) return
      node.children = node.children.flatMap(child => {
        if (child.type !== 'text') { walk(child); return [child] }
        const pieces = []
        let offset = 0
        for (const match of child.value.matchAll(/\[(\d+)\]/g)) {
          if (!allowed.has(Number(match[1]))) continue
          if (match.index > offset) pieces.push({ type: 'text', value: child.value.slice(offset, match.index) })
          pieces.push({ type: 'link', url: `#source-${match[1]}`, children: [{ type: 'text', value: match[0] }] })
          offset = match.index + match[0].length
        }
        if (!pieces.length) return [child]
        if (offset < child.value.length) pieces.push({ type: 'text', value: child.value.slice(offset) })
        return pieces
      })
    }
    walk(tree)
  }
}
