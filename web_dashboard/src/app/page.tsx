import { DashboardHome } from "../components/DashboardHome";
import { loadAllBots } from "../lib/loadBots";

export const dynamic = "force-dynamic";

export default function HomePage() {
  const initial = loadAllBots();
  return <DashboardHome initial={initial} />;
}
