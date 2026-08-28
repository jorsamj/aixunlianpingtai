export function uploadBatchFromResponse(response) {
  const images = Array.isArray(response?.uploaded) ? response.uploaded : [];
  const imageIds = Array.isArray(response?.uploaded_image_ids)
    ? response.uploaded_image_ids.map(String)
    : images.map(image => String(image.id));
  return {
    batchId: response?.batch_id || null,
    imageIds,
    images
  };
}
