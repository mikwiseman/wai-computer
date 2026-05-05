import { OpenWaiSayAppClient } from "@/components/OpenWaiSayAppClient";
import { normalizeWaiSayAppClient } from "@/lib/app-client";

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
      <OpenWaiSayAppClient
        token={params.token ?? null}
        client={normalizeWaiSayAppClient(params.client)}
      />
    </main>
  );
}
