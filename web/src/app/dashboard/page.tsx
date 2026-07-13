import { DashboardClient } from "@/components/DashboardClient";

export const metadata = {
  title: "Dashboard — WaiComputer",
};

export default function DashboardPage() {
  return (
    <div className="container">
      <DashboardClient />
    </div>
  );
}
