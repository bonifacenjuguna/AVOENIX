"""Small authored gazetteer used only to give unfamiliar capitalised names an entity type
(person vs place) so pronoun resolution and selectional checks have something to work with.
It is *not* a knowledge base; world facts live in the Knowledge Engine."""

PLACES = {n.lower() for n in """
France Paris London England Britain Germany Berlin Italy Rome Spain Madrid Portugal Lisbon Kenya Nairobi Uganda Kampala Tanzania
Dodoma Nigeria Lagos Abuja Ghana Accra Egypt Cairo Ethiopia Morocco Algeria Tunisia Senegal Zambia Zimbabwe Rwanda Kigali
Africa Europe Asia America Australia Antarctica Canada Ottawa Mexico Brazil Brasilia Argentina Chile Peru Colombia India Delhi
Mumbai China Beijing Shanghai Japan Tokyo Korea Seoul Russia Moscow Turkey Ankara Istanbul Greece Athens Sweden Stockholm Norway
Oslo Finland Helsinki Denmark Copenhagen Netherlands Amsterdam Belgium Brussels Switzerland Bern Austria Vienna Poland Warsaw
Ireland Dublin Scotland Edinburgh Wales Texas California Florida Ohio Nevada Alaska Hawaii Boston Chicago Seattle Houston Miami
Washington Ottawa Mombasa Kisumu Nakuru Eldoret Arusha Zanzibar Pacific Atlantic Mediterranean Everest Kilimanjaro Sahara
Nile Amazon Thames Danube Rhine Manhattan Brooklyn Broadway Earth Mars Venus Jupiter Saturn Mercury Neptune Uranus Pluto Moon Sun
""".split()}
