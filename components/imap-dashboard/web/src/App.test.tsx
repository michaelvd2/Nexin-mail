import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "./App";

test("toont een geopende mail met Nederlandse breinfuncties en veilige opmaak", () => {
  render(<App />);
  expect(screen.getByRole("heading", { name: "Projectupdate en volgende stappen" })).toBeInTheDocument();
  expect(screen.getByRole("article", { name: "Berichtinhoud" })).toHaveTextContent("ontdekkingsfase");
  expect(screen.getByRole("table")).toHaveTextContent("Ontdekking");
  expect(screen.getByText("Externe afbeelding geblokkeerd")).toBeInTheDocument();
  const strip = screen.getByRole("region", { name: "Brein" });
  expect(strip.querySelector(".brain-mark svg")).toHaveClass("lucide-brain");
  expect(within(strip).getByRole("tab", { name: "Acties" })).toHaveAttribute("aria-selected", "true");
  expect(strip).toHaveTextContent("Highlights"); expect(strip).toHaveTextContent("Antwoord opstellen"); expect(strip).toHaveTextContent("Bronnen");
});

test("toont echte begrensde berichtpreviews in de lijst", () => {
  render(<App />);
  expect(screen.getByRole("option", { name: /Sarah van Dijk/ })).toHaveTextContent("de ontdekkingsfase is afgerond");
  expect(screen.queryByText(/inhoud wordt pas geladen/i)).not.toBeInTheDocument();
});

test("laadt externe afbeeldingen pas na domein- en trackingbevestiging", async () => {
  const user = userEvent.setup(); render(<App />);
  await user.click(screen.getByRole("button", { name: "Afbeeldingen laden (1)" }));
  const dialog = screen.getByRole("dialog", { name: "Externe afbeeldingen voor dit bericht laden?" });
  expect(dialog).toHaveTextContent("images.northstar.example");
  expect(dialog).toHaveTextContent("unieke trackingcode");
  await user.click(within(dialog).getByRole("button", { name: "Actie bevestigen" }));
  expect(await screen.findByRole("img", { name: "Extern geladen afbeelding uit dit bericht" })).toBeInTheDocument();
});

test("downloadt een bijlage alleen na bestandsreview en opent hem nooit", async () => {
  const user = userEvent.setup(); render(<App />);
  await user.click(screen.getByRole("button", { name: /projectplanning\.pdf/ }));
  const dialog = screen.getByRole("dialog", { name: "projectplanning.pdf downloaden?" });
  expect(dialog).toHaveTextContent("Downloads\\Nexin Mail");
  expect(dialog).toHaveTextContent("nooit geopend of uitgevoerd");
  await user.click(within(dialog).getByRole("button", { name: "Actie bevestigen" }));
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("niet echt geschreven of geopend"));
});

test("toont beredeneerde verdachte markeringen zonder veiligheid te claimen", async () => {
  const user = userEvent.setup(); render(<App />); await user.click(screen.getByRole("option", { name: /Beveiligingscentrum/ }));
  expect(screen.getByRole("region", { name: "Uitleg verdachte mail" })).toHaveTextContent("Adviserende phishingmarkering");
  expect(screen.getByText(/misleidend afzenderdomein/)).toBeInTheDocument();
});

test("plaatst berichtacties boven de mail en opent een herstelbare bevestiging", async () => {
  const user = userEvent.setup(); render(<App />);
  const actions = screen.getByRole("region", { name: "Berichtacties" });
  await user.click(screen.getByRole("button", { name: "Naar prullenbak" }));
  expect(actions).toBeInTheDocument();
  const dialog = screen.getByRole("dialog", { name: "Dit bericht naar de prullenbak verplaatsen?" });
  expect(dialog).toHaveTextContent("Sarah van Dijk");
  expect(dialog).toHaveTextContent("Projectupdate en volgende stappen");
  expect(dialog).toHaveTextContent("Permanent verwijderen is niet beschikbaar");
  expect(screen.queryByRole("button", { name: /permanent/i })).not.toBeInTheDocument();
});

test("slaat een concept op en vereist daarna aparte verzendcontrole", async () => {
  const user = userEvent.setup(); render(<App />); await user.click(screen.getByRole("button", { name: "Antwoord opstellen" }));
  await user.type(screen.getByRole("textbox", { name: "Conceptbericht" }), "Bedankt voor de update.");
  await user.click(screen.getByRole("button", { name: "Concept opslaan" }));
  expect(screen.getByRole("dialog", { name: "Dit exacte concept opslaan?" })).toHaveTextContent("nog geen actie");
  await user.click(screen.getByRole("button", { name: "Actie bevestigen" }));
  await waitFor(() => expect(screen.getByText("Opgeslagen in Concepten")).toBeInTheDocument());
  await user.click(screen.getByRole("button", { name: "Controleren vóór verzenden" }));
  const send = screen.getByRole("button", { name: "Deze e-mail verzenden" }); expect(send).toBeDisabled();
  await user.click(screen.getByRole("checkbox", { name: "Ik heb de ontvangers en het bericht gecontroleerd" })); expect(send).toBeEnabled(); await user.click(send);
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("geen e-mail verzonden"));
});

test("nieuw bericht kan pas met ontvanger worden opgeslagen", async () => {
  const user = userEvent.setup(); render(<App />); await user.click(screen.getByRole("button", { name: "Nieuw bericht" }));
  expect(screen.getByRole("heading", { name: "Nieuw bericht" })).toBeInTheDocument(); expect(screen.getByRole("button", { name: "Concept opslaan" })).toBeDisabled();
  await user.type(screen.getByRole("textbox", { name: "Aan" }), "ontvanger@example.test"); expect(screen.getByRole("button", { name: "Concept opslaan" })).toBeEnabled();
});

test("prioriteit vereist een door de gebruiker opgegeven regel", async () => {
  const user = userEvent.setup(); render(<App />); await user.click(screen.getByRole("button", { name: "Instellingen" })); await user.click(screen.getByRole("checkbox", { name: /Prioriteit/ }));
  expect(screen.getByRole("button", { name: "Instelling bevestigen" })).toBeDisabled(); await user.type(screen.getByPlaceholderText("goedkeuring, deadline"), "deadline"); expect(screen.getByRole("button", { name: "Instelling bevestigen" })).toBeEnabled();
});

test("reclametab bundelt reclame en vraagt één bevestiging voor alles", async () => {
  const user = userEvent.setup(); render(<App />); await user.click(screen.getByRole("button", { name: /Reclame2/ }));
  expect(screen.getByRole("region", { name: "Reclameberichten" })).toHaveTextContent("Automatisch ingedeelde reclame");
  expect(screen.getAllByRole("option")).toHaveLength(2);
  await user.click(screen.getByRole("button", { name: "Alle 2 naar prullenbak" }));
  const dialog = screen.getByRole("dialog", { name: "Alle 2 reclamemails naar de prullenbak?" });
  expect(dialog).toHaveTextContent("Ontwerpnieuws");
  expect(dialog).toHaveTextContent("Nieuwsbrief: 30% korting op ontwerptools");
  expect(dialog).toHaveTextContent("Example Shop");
  expect(dialog).toHaveTextContent("Aanbieding van de week");
  expect(dialog).toHaveTextContent("Permanent verwijderen is niet beschikbaar");
});

test("reclamelijst toont afmeldmethode per mail en gebruikt één lijstbevestiging", async () => {
  const user = userEvent.setup(); render(<App />); await user.click(screen.getByRole("button", { name: /Reclame2/ }));
  await user.click(screen.getByRole("button", { name: "Afmelden bij 2" }));
  const dialog = screen.getByRole("dialog", { name: "Afmelden bij 2 reclamelijsten?" });
  expect(within(dialog).getByRole("region", { name: "Voorgestelde reclame-afmeldlijst" })).toHaveTextContent("Veilige éénklik-afmelding");
  expect(dialog).toHaveTextContent("Browserbevestiging door Codex");
  expect(dialog).toHaveTextContent("Geen enkel bericht wordt verplaatst of verwijderd");
  await user.click(within(dialog).getByRole("button", { name: "Actie bevestigen" }));
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("veilig ingepland"));
});

test("onderliggende INBOX-mapnamen worden niet dubbel weergegeven", () => {
  render(<App />); expect(screen.getByRole("button", { name: /Concepten3/ })).toBeInTheDocument(); expect(screen.queryByText("INBOX.Drafts")).not.toBeInTheDocument();
});

test("wisselt compact tussen Acties en Highlights met Acties als standaard", async () => {
  const user = userEvent.setup(); render(<App />);
  const brain = screen.getByRole("region", { name: "Brein" });
  const actionsTab = within(brain).getByRole("tab", { name: "Acties" });
  const highlightsTab = within(brain).getByRole("tab", { name: "Highlights" });
  expect(actionsTab).toHaveAttribute("aria-selected", "true");
  await user.click(actionsTab);
  expect(brain).toHaveTextContent("Planning bevestigen");
  await user.click(highlightsTab);
  const result = screen.getByRole("region", { name: "Brein" });
  expect(highlightsTab).toHaveAttribute("aria-selected", "true");
  expect(result).toHaveTextContent("Ontdekkingsfase is afgerond");
  expect(result).toHaveTextContent("Lokaal versleuteld hergebruikt");
  expect(result.querySelectorAll(".lucide-sparkles")).toHaveLength(0);
  expect(result.querySelectorAll(".lucide-brain")).toHaveLength(3);
  await user.click(actionsTab);
  expect(result).toHaveTextContent("Planning bevestigen");
  await user.click(screen.getByRole("button", { name: "Brein opnieuw berekenen" }));
  expect(result).toHaveTextContent("Nieuw berekend en lokaal versleuteld");
});

test("opent rechtstreeks vanuit Brein een reply-all concept", async () => {
  const user = userEvent.setup(); render(<App />);
  await user.click(within(screen.getByRole("region", { name: "Brein" })).getByRole("button", { name: "Allen beantwoorden" }));
  expect(screen.getByRole("heading", { name: "Concept voor allen" })).toBeInTheDocument();
  expect(screen.getByRole("textbox", { name: "Cc" })).toHaveValue("jamie@example.test, taylor@example.test");
});
