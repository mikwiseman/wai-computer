import { normalizeWaiComputerAppClient } from "@/lib/app-client";
import { AppOpenClient } from "./AppOpenClient";

export const metadata = {
  referrer: "no-referrer",
};

interface AppMagicLinkPageProps {
  searchParams: Promise<{ token?: string; client?: string; locale?: string }>;
}

export default async function AppMagicLinkPage({ searchParams }: AppMagicLinkPageProps) {
  const params = await searchParams;

  return (
    <main className="container auth-page">
      <AppOpenClient
        token={params.token ?? null}
        client={normalizeWaiComputerAppClient(params.client)}
        locale={params.locale ?? null}
      />
    </main>
  );
}
