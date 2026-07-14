// Shared download/deep-link constants so the landing pages and the in-app
// empty state point at the same artifacts. The Russian landing serves a
// locale-specific DMG build.
export const MAC_DMG_URL = "/releases/macos/WaiComputer-latest.dmg";
export const MAC_DMG_URL_RU = "/releases/macos/WaiComputer-ru-latest.dmg";

export function macDmgUrl(locale: "en" | "ru"): string {
  return locale === "ru" ? MAC_DMG_URL_RU : MAC_DMG_URL;
}
