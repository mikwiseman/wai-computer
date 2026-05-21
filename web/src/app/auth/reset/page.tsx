import { ResetPasswordClient } from "./ResetPasswordClient";

export const metadata = {
  referrer: "no-referrer",
};

interface ResetPasswordPageProps {
  searchParams: Promise<{ token?: string; locale?: string }>;
}

export default async function ResetPasswordPage({ searchParams }: ResetPasswordPageProps) {
  const params = await searchParams;

  return (
    <main className="container auth-page">
      <ResetPasswordClient token={params.token ?? null} locale={params.locale ?? null} />
    </main>
  );
}
