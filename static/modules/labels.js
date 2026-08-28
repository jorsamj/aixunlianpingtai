export function activeLabelOptions(labels) {
  return (labels || [])
    .filter(label => label?.code && label.status !== 'disabled' && label.status !== 'inactive')
    .map(label => ({
      code: label.code,
      displayName: label.display_name_zh || label.display_name || label.code
    }));
}
