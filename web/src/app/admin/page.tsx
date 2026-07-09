import type { Metadata } from "next";
import { Suspense } from "react";
import { AdminConsoleClient } from "./AdminConsoleClient";

export const metadata: Metadata = {
  title: "Admin — WaiComputer",
  robots: {
    index: false,
    follow: false,
  },
};

export default function AdminPage() {
  return (
    <Suspense fallback={<main className="admin-console-loading">Loading admin…</main>}>
      <AdminConsoleClient />
    </Suspense>
  );
}
