/**
 * Order suggested role chips: prefer API gap result (backend pins user target first),
 * otherwise prepend the user's typed target when it is non-empty.
 */
export function mergeSuggestedRoles(
  roleInput: string,
  rolesFromApi: string[],
  rolesFromGap: string[] | undefined | null,
): string[] {
  if (rolesFromGap && rolesFromGap.length > 0) return rolesFromGap
  const t = roleInput.trim()
  if (!t || !rolesFromApi.length) return rolesFromApi
  const tl = t.toLowerCase()
  const rest = rolesFromApi.filter((r) => r.trim().toLowerCase() !== tl)
  const titled = t
    .split(/\s+/)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
    .join(' ')
  return [titled, ...rest]
}
