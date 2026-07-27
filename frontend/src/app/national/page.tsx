import { redirect } from "next/navigation";

// The standalone "International Predictions" list was removed — upcoming national
// fixtures are merged into Upcoming and past ones into Recent Results (both have
// an "International" filter), so this page only duplicated them. Match-detail
// pages (/national/[id]) stay. The World Cup pages (/national/world-cup[/review])
// were retired after the 2026 tournament and now redirect here too.
// Kept as a redirect so old links/bookmarks don't 404.
export default function NationalIndex() {
  redirect("/");
}
