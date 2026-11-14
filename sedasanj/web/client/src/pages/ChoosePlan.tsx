import { Navigate } from "react-router-dom";

/** The plan chooser now lives on the checkout page itself; old links keep working. */
export default function ChoosePlan() {
  return <Navigate to="/checkout" replace />;
}
