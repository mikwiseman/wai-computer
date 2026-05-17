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
    <section className="auth-card">
      <div className="auth-card__brand">
        <div className="brand-mark" aria-hidden="true" />
        <span>WaiComputer</span>
      </div>

      <header className="auth-card__header">
        <h1>{mode === "login" ? "Sign In" : "Create Account"}</h1>
      </header>

      <form onSubmit={onSubmit} className="auth-form">
        <label htmlFor="email">
          <span>Email</span>
          <input
            id="email"
            data-testid="auth-email"
            name="email"
            type="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
        </label>

        <label htmlFor="password">
          <span>Password</span>
          <input
            id="password"
            data-testid="auth-password"
            name="password"
            type="password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </label>

        <button className="primary-button" data-testid="auth-submit" type="submit" disabled={loading}>
          {loading ? "Please wait..." : mode === "login" ? "Sign In" : "Create Account"}
        </button>
      </form>

      <div className="auth-card__secondary">
        <button
          className="ghost-button"
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
        <p className="auth-card__message" data-testid="auth-message" role="status">
          {message}
        </p>
      ) : null}
    </section>
  );
}
