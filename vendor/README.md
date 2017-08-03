# Convenience imports

... should check for updates!

## marc2bibframe-xsl

`xsl` directory from <https://github.com/lcnetdev/marc2bibframe2>, which contains the XSL files to convert a MARCXML record to BIBFRAME RDF/XML. Use with:

```
xsltproc vendor/marc2bibframe2-xsl/marc2bibframe2.xsl vendor/bib2lod/102063.min.xml
```

## bib2lod

To rebuild code/data here, from the `bteko2bf` directory, check out, build and copy `https://github.com/ld4l-labs/bib2lod` with:

```
git clone git@github.com:ld4l-labs/bib2lod.git
cd bib2lod
mvn install
cd ..
cp bib2lod/target/bib2lod.jar vendor/bib2lod/
cp bib2lod/test-data/marcxml-to-biblioteko/cornell/minimal-record/102063.min.xml vendor/bib2lod/
```

Also have modified version of `bib2lod/test-data/marcxml-to-biblioteko/config.json` as `vendor/bib2lod/config.json`.
