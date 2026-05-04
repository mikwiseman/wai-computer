import { SharedRecordingClient } from "@/components/SharedRecordingClient";

export default async function SharedRecordingPage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = await params;
  return <SharedRecordingClient token={token} />;
}
