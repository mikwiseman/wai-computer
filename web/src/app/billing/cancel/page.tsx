import Link from "next/link";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Checkout canceled — WaiComputer",
};

export default function BillingCancelPage() {
  return (
    <main className="container">
      <section className="auth-card">
        <h1>Checkout canceled</h1>
        <p>No payment was made. You can restart checkout from Billing when you are ready.</p>
        <Link className="primary-button" href="/billing">
          Open billing
        </Link>
      </section>
    </main>
  );
}
