"""Reused unchanged from LeyZee/the-season-of-revelation (MIT).
Copyright (c) 2026 LeyZee. See LICENSE-LeyZee.txt.
Source: 02-scripts/preparer_minicarte.py, ecrit_tga_palette.
"""

def ecrit_tga_palette(chemin, indices, palette):
    """TGA type 1 (a palette, non compresse), indices sur 16 bits, palette BGRA 32 bits, origine
    en bas — exactement le format des images de correspondance de CA."""
    h, w = indices.shape
    entete = bytearray(18)
    entete[1] = 1                                    # palette presente
    entete[2] = 1                                    # image a palette, non compressee
    entete[5:7] = len(palette).to_bytes(2, "little")
    entete[7] = 32                                   # 32 bits par entree de palette
    entete[12:14] = w.to_bytes(2, "little")
    entete[14:16] = h.to_bytes(2, "little")
    entete[16] = 16                                  # 16 bits par pixel
    # 25.09.2026 (audit des calques, session du rendu) : CA ecrit ses lookups LIGNE 0 = NORD avec l'octet 17 a 0x10
    # (Empires, Chaos : correlation avec la carte peinte 0,31 telle quelle, -0,02 retournee) ; le jeu lit les lignes
    # dans l'ordre du fichier, sans tenir compte de l'origine TGA. Nos lookups etaient ecrits du sud au nord (0,05
    # contre 0,21 retournes) : territoires, frontieres au dezoom et minicarte a l'envers. Meme ordre et meme octet que CA.
    entete[17] = 0x10                                # comme CA (lignes du nord au sud dans le fichier)
    pal = bytearray()
    for r, g, b, a in palette:
        pal += bytes((b, g, r, a))
    donnees = indices.astype("<u2").tobytes()        # lignes du nord au sud, comme CA
    with open(chemin, "wb") as f:
        f.write(bytes(entete) + bytes(pal) + donnees)
