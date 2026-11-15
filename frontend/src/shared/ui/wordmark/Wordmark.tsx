import { Link } from "react-router";
import { APP_NAME, ROUTES } from "@/shared/config";
import logo from "./logo.png";
import s from "./wordmark.module.css";

/** Brand: corn mark on Green 700 + the product name. */
export function Wordmark() {
  return (
    <Link to={ROUTES.home} className={s.wordmark}>
      <img src={logo} alt="" width={35} height={32} className={s.mark} />
      {APP_NAME}
      <span className="visually-hidden">, home</span>
    </Link>
  );
}
