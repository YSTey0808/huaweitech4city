// Shared field validators — used by signup and profile editing so the
// rules can never drift apart.

export const USERNAME_RE = /^[a-z0-9_]{3,20}$/

// SG numbers only, display-only (no OTP): +65 then 8 digits starting 6/8/9.
export const SG_PHONE_RE = /^\+65[689]\d{7}$/
