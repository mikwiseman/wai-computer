"use client";

import { useRouter } from "next/navigation";
import { AuthForm } from "@/components/AuthForm";

export default function RegisterPage() {
  const router = useRouter();

  return (
    <main className="container auth-page">
      <AuthForm mode="register" onSuccess={() => router.replace("/dashboard")} />
    </main>
  );
}
