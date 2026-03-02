"use client";

import { useRouter } from "next/navigation";
import { AuthForm } from "@/components/AuthForm";

export default function LoginPage() {
  const router = useRouter();

  return (
    <main className="container">
      <AuthForm mode="login" onSuccess={() => router.replace("/dashboard")} />
    </main>
  );
}
