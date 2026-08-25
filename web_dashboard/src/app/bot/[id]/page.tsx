import { notFound } from "next/navigation";
import { BotDetailClient } from "../../../components/BotDetailClient";
import { loadBot } from "../../../lib/loadBots";

export const dynamic = "force-dynamic";

export default async function BotPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const bot = loadBot(id);
  if (!bot) notFound();
  return <BotDetailClient initial={bot} />;
}
