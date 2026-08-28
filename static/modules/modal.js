export function createModalStack() {
  const items = [];
  return {
    push: item => items.push(item),
    pop: () => items.pop(),
    peek: () => items.at(-1),
    size: () => items.length
  };
}

