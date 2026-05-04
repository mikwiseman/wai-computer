import { VerifyMagicLinkClient } from "@/components/VerifyMagicLinkClient";

interface VerifyPageProps {
  searchParams: Promise<{ token?: string }>;
}

export default async function VerifyMagicLinkPage({ searchParams }: VerifyPageProps) {
  const params = await searchParams;

  return (
    <main className="container auth-page">
      <VerifyMagicLinkClient token={params.token ?? null} />
    </main>
  );
}
