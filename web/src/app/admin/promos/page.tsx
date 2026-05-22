import type { Metadata } from "next";
import { AdminPromoCodesClient } from "./AdminPromoCodesClient";

export const metadata: Metadata = {
  title: "Admin Promocodes — WaiComputer",
};

export default function AdminPromoCodesPage() {
  return <AdminPromoCodesClient />;
}
