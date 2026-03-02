"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";
import { login, register, requestMagicLink } from "@/lib/api";
import { ApiError } from "@/lib/http";

type Mode = "login" | "register";

interface AuthFormProps {
  mode: Mode;
  onSuccess: () => void;
}

function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Unexpected error";
}

export function AuthForm({ mode, onSuccess }: AuthFormProps) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage(null);
    setLoading(true);

    try {
      if (mode === "login") {
        await login(email, password);
      } else {
        await register(email, password);
      }
      onSuccess();
    } catch (error: unknown) {
      setMessage(describeError(error));
    } finally {
      setLoading(false);
    }
  }

  async function onSendMagicLink() {
    setMessage(null);
    setLoading(true);
    try {
      const response = await requestMagicLink(email);
      setMessage(response.message);
    } catch (error: unknown) {
      setMessage(describeError(error));
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="card">
      <h1>{mode === "login" ? "Sign In" : "Create Account"}</h1>
      <form onSubmit={onSubmit} className="stack">
        <label htmlFor="email">Email</label>
        <input
          id="email"
          data-testid="auth-email"
          name="email"
          type="email"
          required
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />

        <label htmlFor="password">Password</label>
        <input
          id="password"
          data-testid="auth-password"
          name="password"
          type="password"
          required
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />

        <button data-testid="auth-submit" type="submit" disabled={loading}>
          {loading ? "Please wait..." : mode === "login" ? "Sign In" : "Create Account"}
        </button>
      </form>

      <div className="row">
        <button
          data-testid="magic-link-button"
          type="button"
          onClick={onSendMagicLink}
          disabled={loading || email.length === 0}
        >
          Send Magic Link
        </button>
        <Link href={mode === "login" ? "/register" : "/login"}>
          {mode === "login" ? "Need an account?" : "Have an account?"}
        </Link>
      </div>

      {message ? (
        <p data-testid="auth-message" role="status">
          {message}
        </p>
      ) : null}
    </section>
  );
}
