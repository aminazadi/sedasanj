import { isOrgAdmin, useAuth } from "../auth";
import ExtensionsPanel from "../components/ExtensionsPanel";
import { PageHeader } from "../components/PageHeader";

export default function Extensions() {
  const { session } = useAuth();
  return (
    <div className="space-y-4">
      <PageHeader title="داخلی‌ها" description="داخلی‌های همگام‌شده از FreePBX و اختصاص آن‌ها به مخاطب یا اپراتور" />
      <ExtensionsPanel canEdit={isOrgAdmin(session?.role)} />
    </div>
  );
}
