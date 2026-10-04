import { Check } from "lucide-react";

export default function Feedback({
  error,
  notice,
  loading,
}: {
  error: string;
  notice: string;
  loading: boolean;
}) {
  return (
    <>
      {error && (
        <div className="alert error" role="alert">
          {error}
        </div>
      )}
      {notice && (
        <div className="alert success" role="status">
          <Check size={16} />
          {notice}
        </div>
      )}
      {loading && <p className="muted">불러오는 중…</p>}
    </>
  );
}
