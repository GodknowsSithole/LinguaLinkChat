const FALLBACK = "Request failed. Please try again.";
const FIELD_LABELS: Record<string, string> = {
  name: "Full name",
  email: "Email",
  password: "Password",
  preferred_language: "Preferred language",
};

// FastAPI returns strings for HTTP errors and an array of objects for validation.
// Only display the message and field, never the submitted input or error context.
export function formatApiError(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail.map(formatApiError).filter(Boolean).join(" ") || FALLBACK;
  }
  if (detail && typeof detail === "object" && "msg" in detail && typeof detail.msg === "string") {
    const location = "loc" in detail && Array.isArray(detail.loc)
      ? detail.loc.filter((part): part is string | number =>
          (typeof part === "string" || typeof part === "number") && part !== "body")
      : [];
    const field = location.map(part => FIELD_LABELS[String(part)] || String(part)).join(".");
    return field ? `${field}: ${detail.msg}` : detail.msg;
  }
  return FALLBACK;
}
