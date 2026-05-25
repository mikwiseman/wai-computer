import { redirect } from "next/navigation";

export default function AdminPromosPage() {
  redirect("/admin?tab=promos");
}
