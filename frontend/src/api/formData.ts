/**
 * The multipart body every generated upload sends, built the way the server
 * reads it: one field per key, a list as that field repeated, and nothing at
 * all for a value left out. Orval calls this in place of writing the loop into
 * each endpoint (`override.formData` in orval.config.ts).
 */
export const toFormData = <Body>(body: Body): FormData => {
  const form = new FormData();
  for (const [key, value] of Object.entries(body as Record<string, unknown>)) {
    if (value === undefined || value === null) continue;
    for (const item of Array.isArray(value) ? value : [value]) {
      form.append(key, item instanceof Blob ? item : String(item));
    }
  }
  return form;
};
