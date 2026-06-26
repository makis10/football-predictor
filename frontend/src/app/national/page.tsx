import { redirect } from "next/navigation";

// The standalone "International Predictions" list was removed — upcoming national
// fixtures are merged into Upcoming and past ones into Recent Results (both have
// an "International" filter), so this page only duplicated them. Match-detail
// pages (/national/[id]) and the World Cup sim (/national/world-cup) stay.
// Kept as a redirect so old links/bookmarks don't 404.
export default function NationalIndex() {
  redirect("/");
}
