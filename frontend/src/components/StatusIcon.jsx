import Icon from "./Icon";

export default function StatusIcon({ status, size = 17 }) {
  const ok = status !== "error";
  return (
    <span className={"status-icon " + (ok ? "ok" : "error")} style={{ width: size, height: size }}>
      <Icon name={ok ? "check" : "x"} size={Math.max(10, Math.round(size * 0.6))} strokeWidth={3} />
    </span>
  );
}
