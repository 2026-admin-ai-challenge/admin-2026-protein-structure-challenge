import { Trophy } from "lucide-react";
export default function Empty({
  title,
  text,
}: {
  title: string;
  text: string;
}) {
  return (
    <div className="empty">
      <Trophy size={30} />
      <h3>{title}</h3>
      <p>{text}</p>
    </div>
  );
}
