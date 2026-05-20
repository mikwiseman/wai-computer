import Link from "next/link";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Billing updated — WaiComputer",
};

export default function BillingSuccessPage() {
  return (
    <main className="container">
      <section className="auth-card">
        <h1>Billing updated</h1>
        <p>Your payment was accepted. Return to WaiComputer and refresh Billing if the Pro status is not visible yet.</p>
        <Link className="primary-button" href="/billing">
          Open billing
        </Link>
      </section>
    </main>
  );
}
