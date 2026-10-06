/** Helpers for the deployment-level plug-in service registration form. */

/** Split a textarea of origins into the list the API expects. */
export const parseAllowedOrigins = (value: string): string[] =>
  value
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0);

/**
 * Send the browser to the vendor's setup page with the manifest, as the form
 * post the vendor's manifest flow takes. The page leaves for the vendor.
 */
export const postToVendor = (setup: { action: string; manifest: string; state: string }) => {
  const form = document.createElement("form");
  form.method = "post";
  form.action = `${setup.action}?state=${encodeURIComponent(setup.state)}`;
  form.hidden = true;
  const manifest = document.createElement("input");
  manifest.type = "hidden";
  manifest.name = "manifest";
  manifest.value = setup.manifest;
  form.appendChild(manifest);
  document.body.appendChild(form);
  form.submit();
};
