export type WaiSayAppClient = "android" | "ios" | "macos";

const APP_URL_BASE: Record<WaiSayAppClient, string> = {
  android: "waisay://magic",
  ios: "waisay://auth/verify",
  macos: "waisay://auth/verify",
};

export function normalizeWaiSayAppClient(value: string | null | undefined): WaiSayAppClient | null {
  if (value === "android" || value === "ios" || value === "macos") {
    return value;
  }
  return null;
}

export function buildWaiSayAppUrl(token: string, client: WaiSayAppClient): string {
  const url = new URL(APP_URL_BASE[client]);
  url.searchParams.set("token", token);
  return url.toString();
}
