export type WaiComputerAppClient = "android" | "ios" | "macos";

const APP_URL_BASE: Record<WaiComputerAppClient, string> = {
  android: "waicomputer://magic",
  ios: "waicomputer://auth/verify",
  macos: "waicomputer://auth/verify",
};

export function normalizeWaiComputerAppClient(value: string | null | undefined): WaiComputerAppClient | null {
  if (value === "android" || value === "ios" || value === "macos") {
    return value;
  }
  return null;
}

export function buildWaiComputerAppUrl(token: string, client: WaiComputerAppClient): string {
  const url = new URL(APP_URL_BASE[client]);
  url.searchParams.set("token", token);
  return url.toString();
}
