import { OpenWaiComputerAppClient } from "@/components/OpenWaiComputerAppClient";
import { normalizeWaiComputerAppClient } from "@/lib/app-client";

export const metadata = {
  referrer: "no-referrer",
};

interface AppMagicLinkPageProps {
  searchParams: Promise<{ token?: string; client?: string }>;
}

export default async function AppMagicLinkPage({ searchParams }: AppMagicLinkPageProps) {
  const params = await searchParams;

  return (
    <main className="container auth-page">
      <OpenWaiComputerAppClient
        token={params.token ?? null}
        client={normalizeWaiComputerAppClient(params.client)}
      />
    </main>
  );
}
