#!/usr/bin/env python
"""MARC to bibliotek-o Converter Harness.

This code doesn't do any conversion, it is designed to hook
together the LC `marc2bibframe` XSL and `bib2lod`.
"""

import argparse
import io
import logging
import os.path
import pymarc
import pymarc.marcxml
import rdflib
from rdflib.namespace import Namespace, NamespaceManager, RDF
import subprocess
import sys


BF = Namespace('http://id.loc.gov/ontologies/bibframe/')
BIB = Namespace('http://bibliotek-o.org/ontology/')
DCT = Namespace('http://purl.org/dc/terms/')
MADSRDF = Namespace('http://www.loc.gov/mads/rdf/v1#')
VIVO = Namespace('http://vivoweb.org/ontology/core#')


def bind_namespace(g, prefix, namespace):
    """Bind prefix to namespace in ns_mgr."""
    ns = Namespace(namespace)
    g.namespace_manager.bind(prefix, ns, override=False)
    return ns


def tree_remove(g, s, p, o):
    """Modify g to remove (s, p, o) and all children.

    FIXME - this is wildly unsafe because it doesn't worry
    about running into portions of a tree already removed.
    """
    g.remove((s, p, o))
    if (not isinstance(o, rdflib.Literal)):
        s = o
        for (p, o) in g.predicate_objects(s):
            tree_remove(g, s, p, o)


def s_o_replace(g, old_uri, new_uri):
    """Modify g to replace old_uri with new_uri in subject or objects."""
    old = rdflib.URIRef(old_uri)
    new = rdflib.URIRef(new_uri)
    for (s, p, o) in g:
        so = s
        oo = o
        edit = False
        if (s == old):
            s = new
            edit = True
        if (o == old):
            o = new
            edit = True
        if (edit):
            g.remove((so, p, oo))
            g.add((s, p, o))


class Marc2Bteko(object):
    """MARC to bibliotek-o converter harness class."""

    def __init__(self, xsl):
        """Initialize Marc2Bteko object."""
        self.xsl = xsl

    def write_marcxml(self, record, filename):
        """Write record to filename as MARCXML."""
        with open(filename, 'wb') as fh:
            writer = pymarc.XMLWriter(fh)
            writer.write(record)
            writer.close()

    def write_rdf(self, graph, filename, format='turtle'):
        """Write rdflib graph to filename in given format.

        Take care to set up the namespace prefixes we are used to.
        """
        logging.info("Writing %s triples to %s" %
                     (len(graph), filename))
        graph.bind('bib', BIB, override=True)
        graph.bind('dct', DCT, override=True)
        graph.bind('vivo', VIVO, override=True)
        graph.bind('bf', BF, override=True)
        graph.bind('madsrdf', MADSRDF, override=True)
        with open(filename, 'wb') as fh:
            fh.write(graph.serialize(format=format))

    def get_instance_and_work(self, graph, name='', sloppy=False):
        """Extract bf:Instance and bf:Work URIs from graph.

        There MUST be exactly one of each, raise exception otherwise.
        """
        instances = list(graph.subjects(RDF.type, BF.Instance))
        if (len(instances) != 1):
            raise Exception("Expected 1 bf.Instance in %s graph, got %d"
                            (name, len(instances)))
        works = list(graph.subjects(RDF.type, BF.Work))
        if (len(works) != 1):
            raise Exception("Expected 1 bf.Work in %s graph, got %d"
                            (name, len(works)))
        return(instances[0], works[0])

    def convert(self, infilename, outfilename):
        """Wrapper to convert infilename from MARC to bibliotek-o."""
        with open(infilename, 'r') as fh:
            records = pymarc.marcxml.parse_xml_to_array(fh)
        if (len(records) > 1):
            logging.fatal("Oops - can handle only one record at present!")
            sys.exit(1)
        record = records[0]
        (marc_bf, marc_bteko) = self.marc_split(record)
        # Write out for now
        tmp_marc_bf = 'tmp/marc_bf.xml'
        self.write_marcxml(marc_bf, tmp_marc_bf)
        tmp_marc_bteko = 'tmp/marc_bteko.xml'
        self.write_marcxml(marc_bteko, tmp_marc_bteko)
        # BIBFRAME and bibliotek-o partial conversions
        g_bf = self.run_lc_xslt(tmp_marc_bf)
        g_bteko = self.run_bib2lod(tmp_marc_bteko)
        # Merge graphs
        #
        # Add in triples from b_bf to avoid copying namespaces
        # (could just use + operator if I know how to delete bflc namespace)
        (bf_inst, bf_work) = self.get_instance_and_work(g_bf, 'BIBFRAME')
        (bteko_inst, bteko_work) = self.get_instance_and_work(g_bteko, 'bteko')
        s_o_replace(g_bteko, bteko_inst, bf_inst)
        s_o_replace(g_bteko, bteko_work, bf_work)
        for (s, p, o) in g_bf:
            g_bteko.add((s, p, o))
        self.write_rdf(g_bteko, outfilename)

    def run_lc_xslt(self, tmp_marc_bf):
        """Run LC BIBFRAME2 XSLT, return rdflib Graph."""
        with subprocess.Popen('xsltproc %s %s' % (self.xsl, tmp_marc_bf),
                              stdout=subprocess.PIPE,
                              shell=True) as xsltproc:
            bf_rdfxml = xsltproc.stdout.read().decode('utf-8')
            # Write out for debugging
            with open('tmp/marc_bf.rdfxml', 'w') as fh:
                fh.write(bf_rdfxml)
                fh.close()
        g = rdflib.Graph()
        g.parse(io.StringIO(bf_rdfxml))
        # Munge graph to delete triples and descendants with bflc:
        # predicates or bflc: objects. Leaving these in will cause
        # problems because the output for the LC converter refers
        # to bnode bf:Instance objects for bflc:indexedIn description
        # for example.
        for (s, p, o) in g:
            tstr = str(s) + '  ' + str(p) + '  ' + str(o)
            if (str(p).startswith('http://id.loc.gov/ontologies/bflc/')):
                logging.debug('bflc tree discard: ' + tstr)
                tree_remove(g, s, p, o)
            elif (str(o).startswith('http://id.loc.gov/ontologies/bflc/')):
                logging.debug('bflc discard: ' + tstr)
                g.remove((s, p, o))
        logging.info("Have %d triples from BF conversion" % (len(g)))
        return(g)

    def run_bib2lod(self, tmp_marc_bteko):
        """Run bib2lod on input file, return rdflib Graph."""
        # Bibliotek-o conversion
        with subprocess.Popen('java -jar vendor/bib2lod/bib2lod.jar '
                              '-c vendor/bib2lod/config.json '
                              '--set InputService:source=%s '
                              '--set InputService:extension=xml '
                              '--set OutputService:destination=tmp '
                              '--set OutputService:format=TURTLE ' %
                              (tmp_marc_bteko),
                              stdout=subprocess.PIPE,
                              shell=True) as bib2lodproc:
            log = bib2lodproc.stdout.read().decode('utf-8')
            log_lines = log.split("\n")
            if (len(log_lines) > 3):
                for line in log_lines:
                    logging.warn("bib2lod: " + line)
        # Outout only to file with name awkwardluy constructed from
        # input file name (FIXME -- get option to output to STDOUT)
        filename = os.path.split(tmp_marc_bteko)[1]
        bteko_filename = os.path.join('tmp', os.path.splitext(filename)[0] + '.ttl')
        g = rdflib.Graph()
        g.parse(source=bteko_filename, format='turtle')
        logging.info("Have %d triples from bib2lod conversion" % (len(g)))
        return(g)

    def marc_split(self, record):
        """Split record into portions for BIBFRAME and bibliotek-o conversions.

        Most of the record will go to the BF conversion so implement this
        as a cherry-picking process of moving certain fields out into
        a new marc_bteko record.
        """
        marc_bteko = pymarc.Record()
        # Fields to duplicate for both converters
        marc_bteko.leader = record.leader
        for tag in ['001', '008', '245']:
            for field in record.get_fields(tag):
                logging.debug("Extracting %s field for bteko conv" % (tag))
                marc_bteko.add_field(field)
        # Fields to move to record for bib2lod
        for tag in ['260']:
            for field in record.get_fields(tag):
                logging.debug("Extracting %s field for bteko conv" % (tag))
                marc_bteko.add_field(field)
                record.remove_field(field)
        return(record, marc_bteko)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="MARC to bibliotek-o Converter Harness.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('--xsl', action='store',
                        default='vendor/marc2bibframe2-xsl/marc2bibframe2.xsl',
                        help='marc2bibframe XSL')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help="be verbose")
    parser.add_argument('--debug', '-d', action='store_true',
                        help="be very verbose")
    parser.add_argument('filename', nargs=argparse.REMAINDER,
                        help="input MARCXML filename(s)")
    (opts, args) = parser.parse_known_args()
    logging.basicConfig(level=logging.DEBUG if opts.debug else
                        (logging.INFO if opts.verbose else logging.WARN))
    marc2bteko = Marc2Bteko(xsl=opts.xsl)
    for infilename in args:
        (root, ext) = os.path.splitext(os.path.split(infilename)[1])
        outfilename = root + ('' if ext.lower() == '.xml' else ext) + '.ttl'
        logging.info("Converting %s -> %s..." % (infilename, outfilename))
        marc2bteko.convert(infilename, outfilename)
    logging.info("Done.")
