import { VerifyMagicLinkClient } from "@/components/VerifyMagicLinkClient";

export const metadata = {
  referrer: "no-referrer",
};

interface VerifyPageProps {
  searchParams: Promise<{ token?: string; locale?: string; lang?: string }>;
}

export default async function VerifyMagicLinkPage({ searchParams }: VerifyPageProps) {
  const params = await searchParams;

  return (
    <main className="container auth-page">
      <VerifyMagicLinkClient
        token={params.token ?? null}
        locale={params.locale ?? params.lang ?? null}
      />
    </main>
  );
}
