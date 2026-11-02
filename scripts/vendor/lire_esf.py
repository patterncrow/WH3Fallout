#!/usr/bin/env python3
"""
lire_esf.py - lire un fichier ESF de Total War (magie 0xABCB), sans RPFM ni EditSF.

Pourquoi (21.09.2026, journal `phase-2-startpos-temoin.md` § 13) : le startpos plante parce que le
tableau « un enregistrement de 10 octets par hex » du jeu vaut `0xFFFF0000` partout. Ce tableau
est rempli depuis `map_data.esf`. Pour savoir si le defaut vient de MapDataBuilder ou du jeu, il
faut lire le fichier — en particulier les noeuds `REGION_AREAS`, `REGION_AREA_DATA` et
`REGION_AREA_INDEX`.

La grammaire n'a pas ete devinee : elle a ete etablie sur les octets, puis **verifiee** par le fait
que le parcours complet de l'arbre tombe exactement sur la table des noms, sur les trois cartes
disponibles (la notre, le prologue de CA, notre ile d'essai).

    en-tete   : u32 magie | u32 (0) | u32 horodatage | u32 offset de la table des noms
                la racine commence a l'offset 16
    noms      : u16 nombre, puis pour chacun u16 longueur + ASCII
    CAULEB128 : entier, 7 bits par octet, **poids fort en premier**, bit 0x80 = « un autre suit »

    noeud-enregistrement  type & 0x80 :
        si type & 0x20 : u16 nom + u8 version      (forme longue, jamais vue ici)
        sinon          : nom = ((type & 1) << 8) | octet suivant ; version = (type >> 1) & 0x0F
        CAULEB(taille du contenu, comptee apres ce champ)
        si type & 0x40 (bloc) : CAULEB(nombre de groupes), puis chaque groupe = CAULEB(taille) + contenu
    noeud-valeur          type < 0x80 : taille fixe par type (voir TAILLES), ou tableau
        (type & 0x40) : CAULEB(taille en octets) puis les octets bruts

Usage :
    python lire_esf.py --esf <fichier.esf>                    # verifie et resume l'arbre
    python lire_esf.py --esf <fichier.esf> --arbre 3          # affiche l'arbre jusqu'a la profondeur 3
    python lire_esf.py --esf <fichier.esf> --noeud REGION_AREA_INDEX
    python lire_esf.py --esf A.esf --compare B.esf            # compte les noeuds des deux cotes
"""

import argparse
import os
import struct
import sys
from collections import Counter

# taille fixe, en octets, du contenu d'un noeud-valeur simple
SENTINELLE = 0xFFFF

TAILLES = {
    0x01: 1, 0x02: 1, 0x03: 2, 0x04: 4, 0x05: 8,
    0x06: 1, 0x07: 2, 0x08: 4, 0x09: 8,
    0x0A: 4, 0x0B: 8, 0x0C: 8, 0x0D: 12,
    0x0E: 4, 0x0F: 4, 0x10: 2,
    0x12: 0, 0x13: 0, 0x14: 0, 0x15: 0, 0x16: 1, 0x17: 2, 0x18: 3,
    0x19: 0, 0x1A: 1, 0x1B: 2, 0x1C: 3, 0x1D: 0,
    0x21: 4, 0x23: 1, 0x24: 2, 0x25: 4,
}
NOMS_TYPES = {
    0x01: "bool", 0x02: "i8", 0x03: "i16", 0x04: "i32", 0x05: "i64",
    0x06: "u8", 0x07: "u16", 0x08: "u32", 0x09: "u64", 0x0A: "f32", 0x0B: "f64",
    0x0C: "coord2d", 0x0D: "coord3d", 0x0E: "utf16", 0x0F: "ascii", 0x10: "angle",
    0x12: "vrai", 0x13: "faux", 0x14: "u32=0", 0x15: "u32=1", 0x16: "u32/8",
    0x17: "u32/16", 0x18: "u32/24", 0x19: "i32=0", 0x1A: "i32/8", 0x1B: "i32/16",
    0x1C: "i32/24", 0x1D: "f32=0",
}


class Erreur(Exception):
    pass


class Esf:
    def __init__(self, blob):
        self.b = blob
        self.magie, _, self.horodatage, self.off_noms = struct.unpack_from("<IIII", blob, 0)
        # 0xABCA : les fichiers livres par CA dans les packs du jeu.
        # 0xABCB : ce que MapDataBuilder du kit ecrit. Meme disposition d'octets, verifie sur le
        # prologue livre et sur le meme prologue regenere : seules la magie et l'horodatage different.
        if self.magie not in (0xABCA, 0xABCB):
            raise Erreur(f"magie {self.magie:#x} inattendue (attendu 0xABCA ou 0xABCB)")
        self.noms = self._lire_noms()
        self.racine = None
        self.fin_arbre = None

    def _lire_noms(self):
        o = self.off_noms
        n = struct.unpack_from("<H", self.b, o)[0]
        o += 2
        out = []
        for _ in range(n):
            ln = struct.unpack_from("<H", self.b, o)[0]
            o += 2
            out.append(self.b[o:o + ln].decode("latin-1"))
            o += ln
        self.fin_noms = o
        return out

    def cauleb(self, o):
        """Rend (valeur, offset suivant). Poids fort en premier, 0x80 = continuation."""
        v = 0
        for _ in range(8):
            c = self.b[o]
            o += 1
            v = (v << 7) | (c & 0x7F)
            if not (c & 0x80):
                return v, o
        raise Erreur(f"CAULEB128 trop long a {o:#x}")

    def noeud(self, o, profondeur=0):
        """Lit un noeud a l'offset o. Rend (dict, offset suivant)."""
        t = self.b[o]
        debut = o
        o += 1
        if t & 0x80:
            if t & 0x20:
                nom = struct.unpack_from("<H", self.b, o)[0]
                version = self.b[o + 2]
                o += 3
            else:
                nom = ((t & 1) << 8) | self.b[o]
                version = (t >> 1) & 0x0F
                o += 1
            taille, o = self.cauleb(o)
            enfants = []
            if t & 0x40:                                  # bloc d'enregistrements
                nb, o = self.cauleb(o)
                fin = o + taille
                for _ in range(nb):
                    tg, o = self.cauleb(o)
                    fin_g = o + tg
                    groupe = []
                    while o < fin_g:
                        e, o = self.noeud(o, profondeur + 1)
                        groupe.append(e)
                    if o != fin_g:
                        raise Erreur(f"groupe deborde a {o:#x} (attendu {fin_g:#x})")
                    enfants.append({"type": "groupe", "enfants": groupe})
                if o != fin:
                    raise Erreur(f"bloc {self.nom(nom)} deborde a {o:#x} (attendu {fin:#x})")
            else:
                fin = o + taille
                while o < fin:
                    e, o = self.noeud(o, profondeur + 1)
                    enfants.append(e)
                if o != fin:
                    raise Erreur(f"enregistrement {self.nom(nom)} deborde a {o:#x} "
                                 f"(attendu {fin:#x})")
            return {"type": "record", "nom": nom, "version": version, "bloc": bool(t & 0x40),
                    "enfants": enfants, "offset": debut}, o

        if t & 0x40:                                      # tableau
            base = t & 0x3F
            taille, o = self.cauleb(o)
            données = self.b[o:o + taille]
            return {"type": "tableau", "base": base, "octets": taille, "données": données,
                    "offset": debut}, o + taille

        if t not in TAILLES:
            raise Erreur(f"type de noeud inconnu {t:#04x} a {debut:#x}")
        n = TAILLES[t]
        return {"type": "valeur", "base": t, "données": self.b[o:o + n], "offset": debut}, o + n

    def nom(self, i):
        return self.noms[i] if 0 <= i < len(self.noms) else f"?{i}"

    def analyse(self):
        """La racine ne suit pas la meme forme que les autres enregistrements : apres son type et
        son nom viennent **deux octets de plus** (`00 02` sur les trois cartes examinees), puis un
        CAULEB dont la valeur tombe une vingtaine d'octets avant la table des noms — ce n'est donc
        pas la fin de l'arbre. Ses enfants se lisent jusqu'a la table des noms, et **c'est la
        validation** : sur les trois cartes, le parcours tombe exactement dessus, a l'octet pres.
        Les enfants, eux, portent bien une taille relative."""
        t = self.b[16]
        if t != 0x80:
            raise Erreur(f"racine de type {t:#04x}, attendu 0x80")
        nom = self.b[17]
        self.racine_inconnu = struct.unpack_from("<H", self.b, 18)[0]
        self.racine_cauleb, o = self.cauleb(20)
        fin = self.off_noms
        enfants = []
        while o < fin:
            e, o = self.noeud(o, 1)
            enfants.append(e)
        if o != fin:
            raise Erreur(f"la racine deborde : parcours arrete a {o:#x}, "
                         f"table des noms a {fin:#x}")
        self.racine = {"type": "record", "nom": nom, "version": 0, "bloc": False,
                       "enfants": enfants, "offset": 16}
        self.fin_arbre = fin
        return self.racine


def parcours(esf, n, chemin=()):
    """Genere (chemin, noeud) pour tout l'arbre."""
    if n["type"] == "record":
        c = chemin + (esf.nom(n["nom"]),)
        yield c, n
        for e in n["enfants"]:
            yield from parcours(esf, e, c)
    elif n["type"] == "groupe":
        for e in n["enfants"]:
            yield from parcours(esf, e, chemin)
    else:
        yield chemin, n


def valeur_lisible(esf, n):
    if n["type"] == "tableau":
        return f"tableau[{n['base']:#04x}] {n['octets']} octets"
    t, d = n["base"], n["données"]
    nom = NOMS_TYPES.get(t, f"{t:#04x}")
    try:
        if t in (0x03,):
            return f"{nom} {struct.unpack('<h', d)[0]}"
        if t in (0x07, 0x10, 0x17, 0x1B, 0x24):
            return f"{nom} {int.from_bytes(d, 'little')}"
        if t in (0x04, 0x08, 0x0E, 0x0F, 0x21, 0x25):
            return f"{nom} {int.from_bytes(d, 'little')}"
        if t in (0x18, 0x1C):
            # trois octets : poids fort en premier (voir `entier`) ; verifie le 22.09.2026 sur la
            # taille decompressee de `COMPRESSED_DATA_INFO`, exacte dans les deux startpos
            return f"{nom} {int.from_bytes(d, 'big')}"
        if t in (0x16, 0x1A, 0x02, 0x06, 0x01, 0x23):
            return f"{nom} {int.from_bytes(d, 'little')}"
        if t == 0x0A:
            return f"{nom} {struct.unpack('<f', d)[0]:g}"
        if t == 0x0C:
            return f"{nom} ({struct.unpack('<f', d[:4])[0]:g}, {struct.unpack('<f', d[4:])[0]:g})"
    except struct.error:
        pass
    return nom


def affiche(esf, n, profondeur_max, profondeur=0, prefixe=""):
    if profondeur > profondeur_max:
        return
    if n["type"] == "record":
        marque = "bloc " if n["bloc"] else ""
        print(f"{prefixe}{marque}{esf.nom(n['nom'])}  (v{n['version']}, {len(n['enfants'])} enfant(s))")
        for e in n["enfants"][:40]:
            affiche(esf, e, profondeur_max, profondeur + 1, prefixe + "  ")
        if len(n["enfants"]) > 40:
            print(f"{prefixe}  ... {len(n['enfants']) - 40} de plus")
    elif n["type"] == "groupe":
        for e in n["enfants"]:
            affiche(esf, e, profondeur_max, profondeur, prefixe)
    else:
        print(f"{prefixe}{valeur_lisible(esf, n)}")


def lire_chaines(esf):
    """Les deux tables de chaines qui suivent la table des noms.

    Disposition, etablie sur les octets et **verifiee** par le fait que la lecture tombe exactement
    sur la fin du fichier : `u32 nombre d'utf16`, les entrees, `u32 nombre d'ascii`, les entrees.
    Une entree = longueur, octets, puis `u32 index` (l'index est explicite, les chaines ne sont pas
    dans l'ordre).

    **La largeur du champ de longueur depend de la magie** : `u16` pour `0xABCA` (ce que CA livre),
    `u32` pour `0xABCB` (ce que MapDataBuilder du kit ecrit). C'est la seule difference entre les
    deux formats sur ces fichiers — le reste, en-tete, arbre et table des noms, est identique.

    Rend (utf16, ascii, offset de fin), chaque liste etant [(index, texte), ...]."""
    large = 4 if esf.magie == 0xABCB else 2
    b, o = esf.b, esf.fin_noms

    def table(o, utf16):
        n = struct.unpack_from("<I", b, o)[0]
        o += 4
        out = []
        for _ in range(n):
            ln = int.from_bytes(b[o:o + large], "little")
            o += large
            brut = b[o:o + (ln * 2 if utf16 else ln)]
            o += len(brut)
            idx = struct.unpack_from("<I", b, o)[0]
            o += 4
            out.append((idx, brut.decode("utf-16-le" if utf16 else "latin-1", "replace")))
        return out, o

    u, o = table(o, True)
    a, o = table(o, False)
    return u, a, o


def convertir_vers_abca(blob):
    """Reecrit un ESF `0xABCB` du kit en `0xABCA`, le seul format que le jeu consomme.

    Deux changements, et deux seulement : l'octet de magie, et la largeur du champ de longueur des
    tables de chaines (u32 -> u16). L'arbre et la table des noms sont recopies tels quels, donc
    l'offset de la table des noms ne bouge pas. Rend les octets convertis."""
    esf = Esf(blob)
    esf.analyse()
    if esf.magie == 0xABCA:
        return blob
    u, a, fin = lire_chaines(esf)
    if fin != len(blob):
        raise Erreur(f"les tables de chaines finissent a {fin:#x}, le fichier a {len(blob):#x} "
                     f"octets : disposition non reconnue, conversion refusee")
    trop = [t for _, t in u + a if len(t) > 0xFFFF]
    if trop:
        raise Erreur(f"{len(trop)} chaine(s) de plus de 65535 caracteres : u16 ne suffit pas")
    sortie = bytearray(blob[:esf.fin_noms])
    sortie[0:4] = (0xABCA).to_bytes(4, "little")
    for liste, utf16 in ((u, True), (a, False)):
        sortie += struct.pack("<I", len(liste))
        for idx, texte in liste:
            brut = texte.encode("utf-16-le") if utf16 else texte.encode("latin-1", "replace")
            sortie += struct.pack("<H", len(texte))
            sortie += brut
            sortie += struct.pack("<I", idx)
    # controle : le resultat doit se relire entierement, arbre et chaines
    verif = Esf(bytes(sortie))
    verif.analyse()
    _, _, f2 = lire_chaines(verif)
    if f2 != len(sortie):
        raise Erreur("le fichier converti ne se relit pas jusqu'au bout")
    return bytes(sortie)


def entier(n):
    """Valeur entiere d'un noeud-valeur, quel que soit son encodage optimise.

    Attention : les formes sur **trois octets** (0x18, 0x1C) sont rangees poids fort en premier,
    alors que celles sur deux octets (0x17, 0x1B) sont poids faible en premier. Constate, pas
    suppose : le champ « nombre d'hex » de `REGION_DATA` vaut alors exactement le compte lu sur la
    couche Regions pour les 61 regions de notre carte, ce qui ne tient pour aucune autre lecture."""
    t, d = n["base"], n["données"]
    if t in (0x14, 0x19):
        return 0
    if t == 0x15:
        return 1
    return int.from_bytes(d, "big" if t in (0x18, 0x1C) else "little")


def flux_rle(esf):
    """Deroule `REGION_AREA_INDEX_OVERRIDE` : chaque groupe porte un `REGION_AREA_INDEX`
    (deux entiers, la paire que le jeu range a l'offset 0 de son enregistrement par hex) suivi
    d'un entier qui est le nombre de repetitions. C'est mot pour mot le decodeur RLE de
    `Warhammer3+0x270FA76`. Rend (largeur, hauteur, [(A, B, repetitions), ...])."""
    largeur = hauteur = None
    for c, n in parcours(esf, esf.racine):
        if n["type"] == "record" and c[-1] == "HEX_MAP_DATA":
            ent = [e for e in n["enfants"] if e["type"] == "valeur"]
            if len(ent) >= 2:
                largeur, hauteur = entier(ent[0]), entier(ent[1])
            break
    paires = []
    for c, n in parcours(esf, esf.racine):
        if n["type"] == "record" and n["bloc"] and c[-1] == "REGION_AREA_INDEX_OVERRIDE":
            for g in n["enfants"]:
                items = g["enfants"] if g["type"] == "groupe" else [g]
                idx = [e for e in items if e["type"] == "record"]
                cnt = [e for e in items if e["type"] == "valeur"]
                if not idx or not cnt:
                    continue
                vals = [entier(e) for e in idx[0]["enfants"] if e["type"] == "valeur"]
                if len(vals) < 2:
                    continue
                paires.append((vals[0], vals[1], entier(cnt[0])))
            break
    return largeur, hauteur, paires


def charge(chemin):
    with open(chemin, "rb") as f:
        esf = Esf(f.read())
    esf.analyse()
    return esf


def resume(esf, chemin):
    reste = esf.off_noms - esf.fin_arbre
    print(f"{os.path.basename(chemin)} : {len(esf.b)} octets, {len(esf.noms)} nom(s)")
    print(f"  arbre : 16 -> {esf.fin_arbre:#x} ; table des noms a {esf.off_noms:#x} "
          f"(reste {reste} octet(s) entre les deux)")
    compte = Counter()
    octets = Counter()
    for c, n in parcours(esf, esf.racine):
        cle = ".".join(c[-2:]) if n["type"] != "record" else ".".join(c[-1:])
        if n["type"] == "record":
            compte[c[-1]] += 1
        elif n["type"] == "tableau":
            compte[cle + f" [tableau]"] += 1
            octets[cle + f" [tableau]"] += n["octets"]
    return compte, octets


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--esf", required=True)
    ap.add_argument("--compare")
    ap.add_argument("--arbre", type=int, default=None, metavar="PROFONDEUR")
    ap.add_argument("--noeud", help="nom de noeud a detailler")
    ap.add_argument("--chaines", action="store_true",
                    help="lire les deux tables de chaines et verifier qu'on tombe sur la fin")
    ap.add_argument("--convertir", metavar="SORTIE",
                    help="ecrire une copie en 0xABCA, le format que le jeu consomme")
    ap.add_argument("--rle", action="store_true",
                    help="derouler REGION_AREA_INDEX_OVERRIDE, le flux qui remplit le tableau "
                         "par hex du jeu, et verifier que la somme fait bien tous les hex")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    esf = charge(a.esf)
    compte, octets = resume(esf, a.esf)

    if a.arbre is not None:
        print()
        affiche(esf, esf.racine, a.arbre)

    if a.noeud:
        print(f"\nnoeuds « {a.noeud} » :")
        vus = 0
        for c, n in parcours(esf, esf.racine):
            if n["type"] == "record" and c[-1] == a.noeud:
                vus += 1
                if vus <= 5:
                    print(f"  a {n['offset']:#x}, chemin {' > '.join(c)}")
                    affiche(esf, n, 2, prefixe="    ")
            elif n["type"] != "record" and c and c[-1] == a.noeud:
                vus += 1
                if vus <= 8:
                    print(f"  a {n['offset']:#x} : {valeur_lisible(esf, n)}  "
                          f"(sous {' > '.join(c)})")
        print(f"  total : {vus}")

    if a.chaines or a.convertir:
        u, asc, fin = lire_chaines(esf)
        print(f"\ntables de chaines (magie {esf.magie:#x}, longueurs sur "
              f"{4 if esf.magie == 0xABCB else 2} octets) :")
        print(f"  utf16 {len(u)}, ascii {len(asc)} ; lecture finie a {fin:#x} sur "
              f"{len(esf.b):#x} " + ("-> OK, tout le fichier est couvert" if fin == len(esf.b)
                                     else "-> INCOHERENT"))
        for idx, t in asc[:5]:
            print(f"     [{idx}] {t!r}")

    if a.convertir:
        données = convertir_vers_abca(esf.b)
        with open(a.convertir, "wb") as f:
            f.write(données)
        print(f"  ecrit {len(données)} octets dans {a.convertir} "
              f"(source {len(esf.b)} octets, magie {esf.magie:#x} -> 0xabca)")

    if a.rle:
        largeur, hauteur, paires = flux_rle(esf)
        total = (largeur or 0) * (hauteur or 0)
        somme = sum(p[2] for p in paires)
        print(f"\nREGION_AREA_INDEX_OVERRIDE : {len(paires)} enregistrement(s)")
        print(f"  HEX_MAP_DATA annonce {largeur} x {hauteur} = {total} hexes")
        print(f"  somme des repetitions    = {somme}"
              + ("   -> couvre toute la carte" if somme == total else
                 f"   -> IL MANQUE {total - somme} hex" if somme < total else "   -> DEBORDE"))
        vides = sum(p[2] for p in paires if p[0] == SENTINELLE or p[1] == SENTINELLE)
        print(f"  hexes dont la paire porte 0xFFFF : {vides}")
        aa = sorted({p[0] for p in paires})
        bb = sorted({p[1] for p in paires})
        print(f"  premier membre  : {len(aa)} valeur(s) distincte(s), de {aa[0]} a {aa[-1]}")
        print(f"  second membre   : {len(bb)} valeur(s) distincte(s), de {bb[0]} a {bb[-1]}")
        print("  dix premiers enregistrements :")
        for A, B, r in paires[:10]:
            print(f"     ({A}, {B}) x {r}")

    if a.compare:
        autre = charge(a.compare)
        c2, o2 = resume(autre, a.compare)
        print(f"\n{'noeud':44} {os.path.basename(a.esf)[:16]:>18} {os.path.basename(a.compare)[:16]:>18}")
        for cle in sorted(set(compte) | set(c2)):
            print(f"{cle:44} {compte.get(cle, 0):>18d} {c2.get(cle, 0):>18d}")
        if octets or o2:
            print(f"\n{'tableau (octets)':44} {'':>18} {'':>18}")
            for cle in sorted(set(octets) | set(o2)):
                print(f"{cle:44} {octets.get(cle, 0):>18d} {o2.get(cle, 0):>18d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
