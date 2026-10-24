import { Boxes } from "lucide-react";
import { Link } from "react-router-dom";

export default function Brand({ light = false }) {
  return (
    <Link className={`brand ${light ? "brand-light" : ""}`} to="/" aria-label="Optiqo home">
      <span className="brand-mark"><Boxes size={19} strokeWidth={2.2} /></span>
      <span className="brand-name">optiqo<span>.</span></span>
    </Link>
  );
}
