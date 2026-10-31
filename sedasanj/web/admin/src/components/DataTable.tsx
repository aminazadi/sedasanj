import type { TableHTMLAttributes } from "react";
import { PaginatedTable } from "@cbi/web-shared/components/PaginatedTable";
import { useTableOffset, useTablePageSize } from "../lib/useTablePagination";

export function DataTable({ tableId, ...props }: TableHTMLAttributes<HTMLTableElement> & { tableId: string }) {
  const [size, setSize] = useTablePageSize();
  const [offset, setOffset] = useTableOffset(`${tableId}_offset`);
  return <PaginatedTable {...props} size={size} onSize={setSize} offset={offset} onOffset={setOffset} />;
}
