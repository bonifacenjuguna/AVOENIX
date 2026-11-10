"""Curated seed knowledge shipped with AVOENIX.

Provenance is ``seed_curated``: authored by the AVOENIX project and **not independently verified**. It is
deliberately small. AVOENIX will answer "I don't know" for anything outside it, its users' statements and what
it can derive. Every entry is stable, widely documented geography/taxonomy; no opinions, no statistics.
"""

from __future__ import annotations

CAPITALS = [
    ("France", "Paris"), ("Germany", "Berlin"), ("Italy", "Rome"), ("Spain", "Madrid"), ("Portugal", "Lisbon"),
    ("United Kingdom", "London"), ("Ireland", "Dublin"), ("Netherlands", "Amsterdam"), ("Belgium", "Brussels"),
    ("Switzerland", "Bern"), ("Austria", "Vienna"), ("Poland", "Warsaw"), ("Sweden", "Stockholm"), ("Norway", "Oslo"),
    ("Denmark", "Copenhagen"), ("Finland", "Helsinki"), ("Greece", "Athens"), ("Russia", "Moscow"), ("Turkey", "Ankara"),
    ("Egypt", "Cairo"), ("Kenya", "Nairobi"), ("Uganda", "Kampala"), ("Tanzania", "Dodoma"), ("Rwanda", "Kigali"),
    ("Ethiopia", "Addis Ababa"), ("Nigeria", "Abuja"), ("Ghana", "Accra"), ("Morocco", "Rabat"), ("Japan", "Tokyo"),
    ("China", "Beijing"), ("India", "New Delhi"), ("South Korea", "Seoul"), ("Canada", "Ottawa"), ("United States", "Washington"),
    ("Mexico", "Mexico City"), ("Brazil", "Brasilia"), ("Argentina", "Buenos Aires"), ("Chile", "Santiago"), ("Peru", "Lima"),
    ("Colombia", "Bogota"), ("Australia", "Canberra"), ("New Zealand", "Wellington"),
]
LOCATED_IN = [
    ("Paris", "France"), ("Berlin", "Germany"), ("Rome", "Italy"), ("Madrid", "Spain"), ("London", "United Kingdom"),
    ("Nairobi", "Kenya"), ("Cairo", "Egypt"), ("Tokyo", "Japan"), ("Beijing", "China"), ("Ottawa", "Canada"),
    ("France", "Europe"), ("Germany", "Europe"), ("Italy", "Europe"), ("Spain", "Europe"), ("United Kingdom", "Europe"),
    ("Kenya", "Africa"), ("Egypt", "Africa"), ("Nigeria", "Africa"), ("Ghana", "Africa"), ("Japan", "Asia"), ("China", "Asia"),
    ("India", "Asia"), ("Canada", "North America"), ("Mexico", "North America"), ("Brazil", "South America"),
    ("Argentina", "South America"), ("Australia", "Oceania"), ("New Zealand", "Oceania"),
]
TAXONOMY = [  # (kind, parent kind)
    ("dog", "mammal"), ("cat", "mammal"), ("horse", "mammal"), ("whale", "mammal"), ("mammal", "animal"), ("bird", "animal"),
    ("eagle", "bird"), ("penguin", "bird"), ("fish", "animal"), ("reptile", "animal"), ("snake", "reptile"), ("insect", "animal"),
    ("human", "mammal"), ("apple", "fruit"), ("banana", "fruit"), ("orange", "fruit"), ("fruit", "food"),
]
NEGATIVE_TAXONOMY = [("whale", "fish"), ("penguin", "mammal"), ("snake", "mammal"), ("dog", "bird"), ("cat", "bird")]
