# -*- coding: utf-8 -*-
import datetime
from decimal import Decimal
import logging
import os

import pysolr
from django.conf import settings
from django.test import TestCase
from haystack import connections, connection_router, reset_search_queries
from haystack import indexes
from haystack.models import SearchResult
from haystack.query import SearchQuerySet, RelatedSearchQuerySet, SQ
from haystack.utils.loading import UnifiedIndex
from core.models import (MockModel, AnotherMockModel,
                         AFourthMockModel, ASixthMockModel)
from core.tests.mocks import MockSearchResult

test_pickling = True

try:
    import cPickle as pickle
except ImportError:
    try:
        import pickle
    except ImportError:
        test_pickling = False


def clear_solr_index():
    # Wipe it clean.
    print 'Clearing out Solr...'
    raw_solr = pysolr.Solr(settings.HAYSTACK_CONNECTIONS['default']['URL'])
    raw_solr.delete(q='*:*')


class SolrMockSearchIndex(indexes.SearchIndex, indexes.Indexable):
    text = indexes.CharField(document=True, use_template=True)
    name = indexes.CharField(model_attr='author', faceted=True)
    pub_date = indexes.DateField(model_attr='pub_date')

    def get_model(self):
        return MockModel


class SolrMaintainTypeMockSearchIndex(indexes.SearchIndex, indexes.Indexable):
    text = indexes.CharField(document=True, use_template=True)
    month = indexes.CharField(indexed=False)
    pub_date = indexes.DateField(model_attr='pub_date')

    def prepare_month(self, obj):
        return "%02d" % obj.pub_date.month

    def get_model(self):
        return MockModel


class SolrMockModelSearchIndex(indexes.SearchIndex, indexes.Indexable):
    text = indexes.CharField(model_attr='foo', document=True)
    name = indexes.CharField(model_attr='author')
    pub_date = indexes.DateField(model_attr='pub_date')

    def get_model(self):
        return MockModel


class SolrAnotherMockModelSearchIndex(indexes.SearchIndex, indexes.Indexable):
    text = indexes.CharField(document=True)
    name = indexes.CharField(model_attr='author')
    pub_date = indexes.DateField(model_attr='pub_date')

    def get_model(self):
        return AnotherMockModel

    def prepare_text(self, obj):
        return u"You might be searching for the user %s" % obj.author


class SolrBoostMockSearchIndex(indexes.SearchIndex, indexes.Indexable):
    text = indexes.CharField(
        document=True, use_template=True,
        template_name='search/indexes/core/mockmodel_template.txt'
    )
    author = indexes.CharField(model_attr='author', weight=2.0)
    editor = indexes.CharField(model_attr='editor')
    pub_date = indexes.DateField(model_attr='pub_date')

    def get_model(self):
        return AFourthMockModel


class SolrRoundTripSearchIndex(indexes.SearchIndex, indexes.Indexable):
    text = indexes.CharField(document=True, default='')
    name = indexes.CharField()
    is_active = indexes.BooleanField()
    post_count = indexes.IntegerField()
    average_rating = indexes.FloatField()
    price = indexes.DecimalField()
    pub_date = indexes.DateField()
    created = indexes.DateTimeField()
    tags = indexes.MultiValueField()
    sites = indexes.MultiValueField()

    def get_model(self):
        return MockModel

    def prepare(self, obj):
        prepped = super(SolrRoundTripSearchIndex, self).prepare(obj)
        prepped.update({
            'text': 'This is some example text.',
            'name': 'Mister Pants',
            'is_active': True,
            'post_count': 25,
            'average_rating': 3.6,
            'price': Decimal('24.99'),
            'pub_date': datetime.date(2009, 11, 21),
            'created': datetime.datetime(2009, 11, 21, 21, 31, 00),
            'tags': ['staff', 'outdoor', 'activist', 'scientist'],
            'sites': [3, 5, 1],
        })
        return prepped


class SolrComplexFacetsMockSearchIndex(indexes.SearchIndex, indexes.Indexable):
    text = indexes.CharField(document=True, default='')
    name = indexes.CharField(faceted=True)
    is_active = indexes.BooleanField(faceted=True)
    post_count = indexes.IntegerField()
    post_count_i = indexes.FacetIntegerField(facet_for='post_count')
    average_rating = indexes.FloatField(faceted=True)
    pub_date = indexes.DateField(faceted=True)
    created = indexes.DateTimeField(faceted=True)
    sites = indexes.MultiValueField(faceted=True)

    def get_model(self):
        return MockModel


class SolrAutocompleteMockModelSearchIndex(indexes.SearchIndex, indexes.Indexable):
    text = indexes.CharField(model_attr='foo', document=True)
    name = indexes.CharField(model_attr='author')
    pub_date = indexes.DateField(model_attr='pub_date')
    text_auto = indexes.EdgeNgramField(model_attr='foo')
    name_auto = indexes.EdgeNgramField(model_attr='author')

    def get_model(self):
        return MockModel


class SolrSpatialSearchIndex(indexes.SearchIndex, indexes.Indexable):
    text = indexes.CharField(model_attr='name', document=True)
    location = indexes.LocationField()

    def prepare_location(self, obj):
        return "%s,%s" % (obj.lat, obj.lon)

    def get_model(self):
        return ASixthMockModel


class SolrSearchBackendTestCase(TestCase):
    def setUp(self):
        super(SolrSearchBackendTestCase, self).setUp()

        # Wipe it clean.
        self.raw_solr = pysolr.Solr(settings.HAYSTACK_CONNECTIONS['default']['URL'])
        clear_solr_index()

        # Stow.
        self.old_ui = connections['default'].get_unified_index()
        self.ui = UnifiedIndex()
        self.smmi = SolrMockSearchIndex()
        self.smtmmi = SolrMaintainTypeMockSearchIndex()
        self.ui.build(indexes=[self.smmi])
        connections['default']._index = self.ui
        self.sb = connections['default'].get_backend()

        self.sample_objs = []

        for i in xrange(1, 4):
            mock = MockModel()
            mock.id = i
            mock.author = 'daniel%s' % i
            mock.pub_date = datetime.date(2009, 2, 25) - datetime.timedelta(days=i)
            self.sample_objs.append(mock)

    def tearDown(self):
        connections['default']._index = self.old_ui
        super(SolrSearchBackendTestCase, self).tearDown()

    def test_non_silent(self):
        bad_sb = connections['default'].backend('bad', URL='http://omg.wtf.bbq:1000/solr', SILENTLY_FAIL=False, TIMEOUT=1)

        try:
            bad_sb.update(self.smmi, self.sample_objs)
            self.fail()
        except:
            pass

        try:
            bad_sb.remove('core.mockmodel.1')
            self.fail()
        except:
            pass

        try:
            bad_sb.clear()
            self.fail()
        except:
            pass

        try:
            bad_sb.search('foo')
            self.fail()
        except:
            pass

    def test_update(self):
        self.sb.update(self.smmi, self.sample_objs)

        # Check what Solr thinks is there.
        self.assertEqual(self.raw_solr.search('*:*').hits, 3)
        self.assertEqual(self.raw_solr.search('*:*').docs, [
            {
                'django_id': '1',
                'django_ct': 'core.mockmodel',
                'name': 'daniel1',
                'name_exact': 'daniel1',
                'text': 'Indexed!\n1',
                'pub_date': '2009-02-24T00:00:00Z',
                'id': 'core.mockmodel.1'
            },
            {
                'django_id': '2',
                'django_ct': 'core.mockmodel',
                'name': 'daniel2',
                'name_exact': 'daniel2',
                'text': 'Indexed!\n2',
                'pub_date': '2009-02-23T00:00:00Z',
                'id': 'core.mockmodel.2'
            },
            {
                'django_id': '3',
                'django_ct': 'core.mockmodel',
                'name': 'daniel3',
                'name_exact': 'daniel3',
                'text': 'Indexed!\n3',
                'pub_date': '2009-02-22T00:00:00Z',
                'id': 'core.mockmodel.3'
            }
        ])

    def test_remove(self):
        self.sb.update(self.smmi, self.sample_objs)
        self.assertEqual(self.raw_solr.search('*:*').hits, 3)

        self.sb.remove(self.sample_objs[0])
        self.assertEqual(self.raw_solr.search('*:*').hits, 2)
        self.assertEqual(self.raw_solr.search('*:*').docs, [
            {
                'django_id': '2',
                'django_ct': 'core.mockmodel',
                'name': 'daniel2',
                'name_exact': 'daniel2',
                'text': 'Indexed!\n2',
                'pub_date': '2009-02-23T00:00:00Z',
                'id': 'core.mockmodel.2'
            },
            {
                'django_id': '3',
                'django_ct': 'core.mockmodel',
                'name': 'daniel3',
                'name_exact': 'daniel3',
                'text': 'Indexed!\n3',
                'pub_date': '2009-02-22T00:00:00Z',
                'id': 'core.mockmodel.3'
            }
        ])

    def test_clear(self):
        self.sb.update(self.smmi, self.sample_objs)
        self.assertEqual(self.raw_solr.search('*:*').hits, 3)

        self.sb.clear()
        self.assertEqual(self.raw_solr.search('*:*').hits, 0)

        self.sb.update(self.smmi, self.sample_objs)
        self.assertEqual(self.raw_solr.search('*:*').hits, 3)

        self.sb.clear([AnotherMockModel])
        self.assertEqual(self.raw_solr.search('*:*').hits, 3)

        self.sb.clear([MockModel])
        self.assertEqual(self.raw_solr.search('*:*').hits, 0)

        self.sb.update(self.smmi, self.sample_objs)
        self.assertEqual(self.raw_solr.search('*:*').hits, 3)

        self.sb.clear([AnotherMockModel, MockModel])
        self.assertEqual(self.raw_solr.search('*:*').hits, 0)

    def test_search(self):
        self.sb.update(self.smmi, self.sample_objs)
        self.assertEqual(self.raw_solr.search('*:*').hits, 3)

        self.assertEqual(self.sb.search(''), {'hits': 0, 'results': []})
        self.assertEqual(self.sb.search('*:*')['hits'], 3)
        self.assertEqual([result.pk for result in self.sb.search('*:*')['results']], ['1', '2', '3'])

        self.assertEqual(self.sb.search('', highlight=True), {'hits': 0, 'results': []})
        self.assertEqual(self.sb.search('Index', highlight=True)['hits'], 3)
        self.assertEqual([result.highlighted['text'][0] for result in self.sb.search('Index', highlight=True)['results']], ['<em>Indexed</em>!\n1', '<em>Indexed</em>!\n2', '<em>Indexed</em>!\n3'])

        self.assertEqual(self.sb.search('Indx')['hits'], 0)
        self.assertEqual(self.sb.search('indax')['spelling_suggestion'], 'index')
        self.assertEqual(self.sb.search('Indx', spelling_query='indexy')['spelling_suggestion'], 'index')

        self.assertEqual(self.sb.search('', facets=['name']), {'hits': 0, 'results': []})
        results = self.sb.search('Index', facets=['name'])
        self.assertEqual(results['hits'], 3)
        self.assertEqual(results['facets']['fields']['name'], [('daniel1', 1), ('daniel2', 1), ('daniel3', 1)])

        self.assertEqual(self.sb.search('', date_facets={'pub_date': {'start_date': datetime.date(2008, 2, 26), 'end_date': datetime.date(2008, 3, 26), 'gap_by': 'month', 'gap_amount': 1}}), {'hits': 0, 'results': []})
        results = self.sb.search('Index', date_facets={'pub_date': {'start_date': datetime.date(2008, 2, 26), 'end_date': datetime.date(2008, 3, 26), 'gap_by': 'month', 'gap_amount': 1}})
        self.assertEqual(results['hits'], 3)
        # DRL_TODO: Correct output but no counts. Another case of needing better test data?
        # self.assertEqual(results['facets']['dates']['pub_date'], {'end': '2008-02-26T00:00:00Z', 'gap': '/MONTH'})

        self.assertEqual(self.sb.search('', query_facets=[('name', '[* TO e]')]), {'hits': 0, 'results': []})
        results = self.sb.search('Index', query_facets=[('name', '[* TO e]')])
        self.assertEqual(results['hits'], 3)
        self.assertEqual(results['facets']['queries'], {'name:[* TO e]': 3})

        self.assertEqual(self.sb.search('', narrow_queries=set(['name:daniel1'])), {'hits': 0, 'results': []})
        results = self.sb.search('Index', narrow_queries=set(['name:daniel1']))
        self.assertEqual(results['hits'], 1)

        # Ensure that swapping the ``result_class`` works.
        self.assertTrue(isinstance(self.sb.search(u'index document', result_class=MockSearchResult)['results'][0], MockSearchResult))

        # Check the use of ``limit_to_registered_models``.
        self.assertEqual(self.sb.search('', limit_to_registered_models=False), {'hits': 0, 'results': []})
        self.assertEqual(self.sb.search('*:*', limit_to_registered_models=False)['hits'], 3)
        self.assertEqual([result.pk for result in self.sb.search('*:*', limit_to_registered_models=False)['results']], ['1', '2', '3'])

        # Stow.
        old_limit_to_registered_models = getattr(settings, 'HAYSTACK_LIMIT_TO_REGISTERED_MODELS', True)
        settings.HAYSTACK_LIMIT_TO_REGISTERED_MODELS = False

        self.assertEqual(self.sb.search(''), {'hits': 0, 'results': []})
        self.assertEqual(self.sb.search('*:*')['hits'], 3)
        self.assertEqual([result.pk for result in self.sb.search('*:*')['results']], ['1', '2', '3'])

        # Restore.
        settings.HAYSTACK_LIMIT_TO_REGISTERED_MODELS = old_limit_to_registered_models

    def test_more_like_this(self):
        self.sb.update(self.smmi, self.sample_objs)
        self.assertEqual(self.raw_solr.search('*:*').hits, 3)

        # A functional MLT example with enough data to work is below. Rely on
        # this to ensure the API is correct enough.
        self.assertEqual(self.sb.more_like_this(self.sample_objs[0])['hits'], 0)
        self.assertEqual([result.pk for result in self.sb.more_like_this(self.sample_objs[0])['results']], [])

    def test_build_schema(self):
        old_ui = connections['default'].get_unified_index()

        (content_field_name, fields) = self.sb.build_schema(old_ui.all_searchfields())
        self.assertEqual(content_field_name, 'text')
        self.assertEqual(len(fields), 4)
        self.assertEqual(fields, [
            {
                'indexed': 'true',
                'type': 'text_en',
                'stored': 'true',
                'field_name': 'text',
                'multi_valued': 'false'
            },
            {
                'indexed': 'true',
                'type': 'date',
                'stored': 'true',
                'field_name': 'pub_date',
                'multi_valued': 'false'
            },
            {
                'indexed': 'true',
                'type': 'text_en',
                'stored': 'true',
                'field_name': 'name',
                'multi_valued': 'false'
            },
            {
                'indexed': 'true',
                'field_name': 'name_exact',
                'stored': 'true',
                'type': 'string',
                'multi_valued': 'false'
            }
        ])

        ui = UnifiedIndex()
        ui.build(indexes=[SolrComplexFacetsMockSearchIndex()])
        (content_field_name, fields) = self.sb.build_schema(ui.all_searchfields())
        self.assertEqual(content_field_name, 'text')
        self.assertEqual(len(fields), 15)
        fields = sorted(fields, key=lambda field: field['field_name'])
        self.assertEqual(fields, [
            {
                'field_name': 'average_rating',
                'indexed': 'true',
                'multi_valued': 'false',
                'stored': 'true',
                'type': 'float'
            },
            {
                'field_name': 'average_rating_exact',
                'indexed': 'true',
                'multi_valued': 'false',
                'stored': 'true',
                'type': 'float'
            },
            {
                'field_name': 'created',
                'indexed': 'true',
                'multi_valued': 'false',
                'stored': 'true',
                'type': 'date'
            },
            {
                'field_name': 'created_exact',
                'indexed': 'true',
                'multi_valued': 'false',
                'stored': 'true',
                'type': 'date'
            },
            {
                'field_name': 'is_active',
                'indexed': 'true',
                'multi_valued': 'false',
                'stored': 'true',
                'type': 'boolean'
            },
            {
                'field_name': 'is_active_exact',
                'indexed': 'true',
                'multi_valued': 'false',
                'stored': 'true',
                'type': 'boolean'
            },
            {
                'field_name': 'name',
                'indexed': 'true',
                'multi_valued': 'false',
                'stored': 'true',
                'type': 'text_en'
            },
            {
                'field_name': 'name_exact',
                'indexed': 'true',
                'multi_valued': 'false',
                'stored': 'true',
                'type': 'string'
            },
            {
                'field_name': 'post_count',
                'indexed': 'true',
                'multi_valued': 'false',
                'stored': 'true',
                'type': 'long'
            },
            {
                'field_name': 'post_count_i',
                'indexed': 'true',
                'multi_valued': 'false',
                'stored': 'true',
                'type': 'long'
            },
            {
                'field_name': 'pub_date',
                'indexed': 'true',
                'multi_valued': 'false',
                'stored': 'true',
                'type': 'date'
            },
            {
                'field_name': 'pub_date_exact',
                'indexed': 'true',
                'multi_valued': 'false',
                'stored': 'true',
                'type': 'date'
            },
            {
                'field_name': 'sites',
                'indexed': 'true',
                'multi_valued': 'true',
                'stored': 'true',
                'type': 'text_en'
            },
            {
                'field_name': 'sites_exact',
                'indexed': 'true',
                'multi_valued': 'true',
                'stored': 'true',
                'type': 'string'
            },
            {
                'field_name': 'text',
                'indexed': 'true',
                'multi_valued': 'false',
                'stored': 'true',
                'type': 'text_en'
            }
        ])

    def test_verify_type(self):
        old_ui = connections['default'].get_unified_index()
        ui = UnifiedIndex()
        smtmmi = SolrMaintainTypeMockSearchIndex()
        ui.build(indexes=[smtmmi])
        connections['default']._index = ui
        sb = connections['default'].get_backend()
        sb.update(smtmmi, self.sample_objs)

        self.assertEqual(sb.search('*:*')['hits'], 3)
        self.assertEqual([result.month for result in sb.search('*:*')['results']], [u'02', u'02', u'02'])
        connections['default']._index = old_ui


class CaptureHandler(logging.Handler):
    logs_seen = []

    def emit(self, record):
        CaptureHandler.logs_seen.append(record)


class FailedSolrSearchBackendTestCase(TestCase):
    def test_all_cases(self):
        self.sample_objs = []

        for i in xrange(1, 4):
            mock = MockModel()
            mock.id = i
            mock.author = 'daniel%s' % i
            mock.pub_date = datetime.date(2009, 2, 25) - datetime.timedelta(days=i)
            self.sample_objs.append(mock)

        # Stow.
        # Point the backend at a URL that doesn't exist so we can watch the
        # sparks fly.
        old_solr_url = settings.HAYSTACK_CONNECTIONS['default']['URL']
        settings.HAYSTACK_CONNECTIONS['default']['URL'] = "%s/foo/" % old_solr_url
        cap = CaptureHandler()
        logging.getLogger('haystack').addHandler(cap)
        import haystack
        logging.getLogger('haystack').removeHandler(haystack.stream)

        # Setup the rest of the bits.
        old_ui = connections['default'].get_unified_index()
        ui = UnifiedIndex()
        smmi = SolrMockSearchIndex()
        ui.build(indexes=[smmi])
        connections['default']._index = ui
        sb = connections['default'].get_backend()

        # Prior to the addition of the try/except bits, these would all fail miserably.
        self.assertEqual(len(CaptureHandler.logs_seen), 0)
        sb.update(smmi, self.sample_objs)
        self.assertEqual(len(CaptureHandler.logs_seen), 1)
        sb.remove(self.sample_objs[0])
        self.assertEqual(len(CaptureHandler.logs_seen), 2)
        sb.search('search')
        self.assertEqual(len(CaptureHandler.logs_seen), 3)
        sb.more_like_this(self.sample_objs[0])
        self.assertEqual(len(CaptureHandler.logs_seen), 4)
        sb.clear([MockModel])
        self.assertEqual(len(CaptureHandler.logs_seen), 5)
        sb.clear()
        self.assertEqual(len(CaptureHandler.logs_seen), 6)

        # Restore.
        settings.HAYSTACK_CONNECTIONS['default']['URL'] = old_solr_url
        connections['default']._index = old_ui
        logging.getLogger('haystack').removeHandler(cap)
        logging.getLogger('haystack').addHandler(haystack.stream)


class LiveSolrSearchQueryTestCase(TestCase):
    fixtures = ['initial_data.json']

    def setUp(self):
        super(LiveSolrSearchQueryTestCase, self).setUp()

        # Wipe it clean.
        clear_solr_index()

        # Stow.
        self.old_ui = connections['default'].get_unified_index()
        self.ui = UnifiedIndex()
        self.smmi = SolrMockSearchIndex()
        self.ui.build(indexes=[self.smmi])
        connections['default']._index = self.ui
        self.sb = connections['default'].get_backend()
        self.sq = connections['default'].get_query()

        # Force indexing of the content.
        self.smmi.update()

    def tearDown(self):
        connections['default']._index = self.old_ui
        super(LiveSolrSearchQueryTestCase, self).tearDown()

    def test_get_spelling(self):
        self.sq.add_filter(SQ(content='Indexy'))
        self.assertEqual(self.sq.get_spelling_suggestion(), u'index')
        self.assertEqual(self.sq.get_spelling_suggestion('indexy'), u'index')

    def test_log_query(self):
        from django.conf import settings
        reset_search_queries()
        self.assertEqual(len(connections['default'].queries), 0)

        # Stow.
        old_debug = settings.DEBUG
        settings.DEBUG = False

        len(self.sq.get_results())
        self.assertEqual(len(connections['default'].queries), 0)

        settings.DEBUG = True
        # Redefine it to clear out the cached results.
        self.sq = connections['default'].query()
        self.sq.add_filter(SQ(name='bar'))
        len(self.sq.get_results())
        self.assertEqual(len(connections['default'].queries), 1)
        self.assertEqual(connections['default'].queries[0]['query_string'], 'name:bar')

        # And again, for good measure.
        self.sq = connections['default'].query()
        self.sq.add_filter(SQ(name='bar'))
        self.sq.add_filter(SQ(text='moof'))
        len(self.sq.get_results())
        self.assertEqual(len(connections['default'].queries), 2)
        self.assertEqual(connections['default'].queries[0]['query_string'], 'name:bar')
        self.assertEqual(connections['default'].queries[1]['query_string'], u'(name:bar AND text:moof)')

        # Restore.
        settings.DEBUG = old_debug


lssqstc_all_loaded = None


class LiveSolrSearchQuerySetTestCase(TestCase):
    """Used to test actual implementation details of the SearchQuerySet."""
    fixtures = ['bulk_data.json']

    def setUp(self):
        super(LiveSolrSearchQuerySetTestCase, self).setUp()

        # Stow.
        self.old_debug = settings.DEBUG
        settings.DEBUG = True
        self.old_ui = connections['default'].get_unified_index()
        self.ui = UnifiedIndex()
        self.smmi = SolrMockSearchIndex()
        self.ui.build(indexes=[self.smmi])
        connections['default']._index = self.ui

        self.sqs = SearchQuerySet()
        self.rsqs = RelatedSearchQuerySet()

        # Ugly but not constantly reindexing saves us almost 50% runtime.
        global lssqstc_all_loaded

        if lssqstc_all_loaded is None:
            print 'Reloading data...'
            lssqstc_all_loaded = True

            # Wipe it clean.
            clear_solr_index()

            # Force indexing of the content.
            self.smmi.update()

    def tearDown(self):
        # Restore.
        connections['default']._index = self.old_ui
        settings.DEBUG = self.old_debug
        super(LiveSolrSearchQuerySetTestCase, self).tearDown()

    def test_load_all(self):
        sqs = self.sqs.load_all()
        self.assertTrue(isinstance(sqs, SearchQuerySet))
        self.assertTrue(len(sqs) > 0)
        self.assertEqual(sqs[0].object.foo, u"Registering indexes in Haystack is very similar to registering models and ``ModelAdmin`` classes in the `Django admin site`_.  If you want to override the default indexing behavior for your model you can specify your own ``SearchIndex`` class.  This is useful for ensuring that future-dated or non-live content is not indexed and searchable. Our ``Note`` model has a ``pub_date`` field, so let's update our code to include our own ``SearchIndex`` to exclude indexing future-dated notes:")

    def test_iter(self):
        reset_search_queries()
        self.assertEqual(len(connections['default'].queries), 0)
        sqs = self.sqs.all()
        results = [int(result.pk) for result in sqs]
        self.assertEqual(results, range(1, 24))
        self.assertEqual(len(connections['default'].queries), 3)

    def test_slice(self):
        reset_search_queries()
        self.assertEqual(len(connections['default'].queries), 0)
        results = self.sqs.all()
        self.assertEqual([int(result.pk) for result in results[1:11]], [2, 3, 4, 5, 6, 7, 8, 9, 10, 11])
        self.assertEqual(len(connections['default'].queries), 1)

        reset_search_queries()
        self.assertEqual(len(connections['default'].queries), 0)
        results = self.sqs.all()
        self.assertEqual(int(results[21].pk), 22)
        self.assertEqual(len(connections['default'].queries), 1)

    def test_count(self):
        reset_search_queries()
        self.assertEqual(len(connections['default'].queries), 0)
        sqs = self.sqs.all()
        self.assertEqual(sqs.count(), 23)
        self.assertEqual(sqs.count(), 23)
        self.assertEqual(len(sqs), 23)
        self.assertEqual(sqs.count(), 23)
        # Should only execute one query to count the length of the result set.
        self.assertEqual(len(connections['default'].queries), 1)

    def test_manual_iter(self):
        results = self.sqs.all()

        reset_search_queries()
        self.assertEqual(len(connections['default'].queries), 0)
        results = [int(result.pk) for result in results._manual_iter()]
        self.assertEqual(results, range(1, 24))
        self.assertEqual(len(connections['default'].queries), 3)

    def test_fill_cache(self):
        reset_search_queries()
        self.assertEqual(len(connections['default'].queries), 0)
        results = self.sqs.all()
        self.assertEqual(len(results._result_cache), 0)
        self.assertEqual(len(connections['default'].queries), 0)
        results._fill_cache(0, 10)
        self.assertEqual(len([result for result in results._result_cache if result is not None]), 10)
        self.assertEqual(len(connections['default'].queries), 1)
        results._fill_cache(10, 20)
        self.assertEqual(len([result for result in results._result_cache if result is not None]), 20)
        self.assertEqual(len(connections['default'].queries), 2)

    def test_cache_is_full(self):
        reset_search_queries()
        self.assertEqual(len(connections['default'].queries), 0)
        self.assertEqual(self.sqs._cache_is_full(), False)
        results = self.sqs.all()
        fire_the_iterator_and_fill_cache = [result for result in results]
        self.assertEqual(results._cache_is_full(), True)
        self.assertEqual(len(connections['default'].queries), 3)

    def test___and__(self):
        sqs1 = self.sqs.filter(content='foo')
        sqs2 = self.sqs.filter(content='bar')
        sqs = sqs1 & sqs2

        self.assertTrue(isinstance(sqs, SearchQuerySet))
        self.assertEqual(len(sqs.query.query_filter), 2)
        self.assertEqual(sqs.query.build_query(), u'(foo AND bar)')

        # Now for something more complex...
        sqs3 = self.sqs.exclude(title='moof').filter(SQ(content='foo') | SQ(content='baz'))
        sqs4 = self.sqs.filter(content='bar')
        sqs = sqs3 & sqs4

        self.assertTrue(isinstance(sqs, SearchQuerySet))
        self.assertEqual(len(sqs.query.query_filter), 3)
        self.assertEqual(sqs.query.build_query(), u'(NOT (title:moof) AND (foo OR baz) AND bar)')

    def test___or__(self):
        sqs1 = self.sqs.filter(content='foo')
        sqs2 = self.sqs.filter(content='bar')
        sqs = sqs1 | sqs2

        self.assertTrue(isinstance(sqs, SearchQuerySet))
        self.assertEqual(len(sqs.query.query_filter), 2)
        self.assertEqual(sqs.query.build_query(), u'(foo OR bar)')

        # Now for something more complex...
        sqs3 = self.sqs.exclude(title='moof').filter(SQ(content='foo') | SQ(content='baz'))
        sqs4 = self.sqs.filter(content='bar').models(MockModel)
        sqs = sqs3 | sqs4

        self.assertTrue(isinstance(sqs, SearchQuerySet))
        self.assertEqual(len(sqs.query.query_filter), 2)
        self.assertEqual(sqs.query.build_query(), u'((NOT (title:moof) AND (foo OR baz)) OR bar)')

    def test_auto_query(self):
        # Ensure bits in exact matches get escaped properly as well.
        # This will break horrifically if escaping isn't working.
        sqs = self.sqs.auto_query('"pants:rule"')
        self.assertTrue(isinstance(sqs, SearchQuerySet))
        self.assertEqual(repr(sqs.query.query_filter), '<SQ: AND content__contains="pants:rule">')
        self.assertEqual(sqs.query.build_query(), u'"pants\\:rule"')
        self.assertEqual(len(sqs), 0)

    # Regressions

    def test_regression_proper_start_offsets(self):
        sqs = self.sqs.filter(text='index')
        self.assertNotEqual(sqs.count(), 0)

        id_counts = {}

        for item in sqs:
            if item.id in id_counts:
                id_counts[item.id] += 1
            else:
                id_counts[item.id] = 1

        for key, value in id_counts.items():
            if value > 1:
                self.fail("Result with id '%s' seen more than once in the results." % key)

    def test_regression_raw_search_breaks_slicing(self):
        sqs = self.sqs.raw_search('text: index')
        page_1 = [result.pk for result in sqs[0:10]]
        page_2 = [result.pk for result in sqs[10:20]]

        for pk in page_2:
            if pk in page_1:
                self.fail("Result with id '%s' seen more than once in the results." % pk)

    # RelatedSearchQuerySet Tests

    def test_related_load_all(self):
        sqs = self.rsqs.load_all()
        self.assertTrue(isinstance(sqs, SearchQuerySet))
        self.assertTrue(len(sqs) > 0)
        self.assertEqual(sqs[0].object.foo, u"Registering indexes in Haystack is very similar to registering models and ``ModelAdmin`` classes in the `Django admin site`_.  If you want to override the default indexing behavior for your model you can specify your own ``SearchIndex`` class.  This is useful for ensuring that future-dated or non-live content is not indexed and searchable. Our ``Note`` model has a ``pub_date`` field, so let's update our code to include our own ``SearchIndex`` to exclude indexing future-dated notes:")

    def test_related_load_all_queryset(self):
        sqs = self.rsqs.load_all()
        self.assertEqual(len(sqs._load_all_querysets), 0)

        sqs = sqs.load_all_queryset(MockModel, MockModel.objects.filter(id__gt=1))
        self.assertTrue(isinstance(sqs, SearchQuerySet))
        self.assertEqual(len(sqs._load_all_querysets), 1)
        self.assertEqual([obj.object.id for obj in sqs], range(2, 24))

        sqs = sqs.load_all_queryset(MockModel, MockModel.objects.filter(id__gt=10))
        self.assertTrue(isinstance(sqs, SearchQuerySet))
        self.assertEqual(len(sqs._load_all_querysets), 1)
        self.assertEqual([obj.object.id for obj in sqs], range(11, 24))
        self.assertEqual([obj.object.id for obj in sqs[10:20]], [21, 22, 23])

    def test_related_iter(self):
        reset_search_queries()
        self.assertEqual(len(connections['default'].queries), 0)
        sqs = self.rsqs.all()
        results = [int(result.pk) for result in sqs]
        self.assertEqual(results, range(1, 24))
        self.assertEqual(len(connections['default'].queries), 4)

    def test_related_slice(self):
        reset_search_queries()
        self.assertEqual(len(connections['default'].queries), 0)
        results = self.rsqs.all()
        self.assertEqual([int(result.pk) for result in results[1:11]], [2, 3, 4, 5, 6, 7, 8, 9, 10, 11])
        self.assertEqual(len(connections['default'].queries), 3)

        reset_search_queries()
        self.assertEqual(len(connections['default'].queries), 0)
        results = self.rsqs.all()
        self.assertEqual(int(results[21].pk), 22)
        self.assertEqual(len(connections['default'].queries), 4)

        reset_search_queries()
        self.assertEqual(len(connections['default'].queries), 0)
        results = self.rsqs.all()
        self.assertEqual([int(result.pk) for result in results[20:30]], [21, 22, 23])
        self.assertEqual(len(connections['default'].queries), 4)

    def test_related_manual_iter(self):
        results = self.rsqs.all()

        reset_search_queries()
        self.assertEqual(len(connections['default'].queries), 0)
        results = [int(result.pk) for result in results._manual_iter()]
        self.assertEqual(results, range(1, 24))
        self.assertEqual(len(connections['default'].queries), 4)

    def test_related_fill_cache(self):
        reset_search_queries()
        self.assertEqual(len(connections['default'].queries), 0)
        results = self.rsqs.all()
        self.assertEqual(len(results._result_cache), 0)
        self.assertEqual(len(connections['default'].queries), 0)
        results._fill_cache(0, 10)
        self.assertEqual(len([result for result in results._result_cache if result is not None]), 10)
        self.assertEqual(len(connections['default'].queries), 1)
        results._fill_cache(10, 20)
        self.assertEqual(len([result for result in results._result_cache if result is not None]), 20)
        self.assertEqual(len(connections['default'].queries), 2)

    def test_related_cache_is_full(self):
        reset_search_queries()
        self.assertEqual(len(connections['default'].queries), 0)
        self.assertEqual(self.rsqs._cache_is_full(), False)
        results = self.rsqs.all()
        fire_the_iterator_and_fill_cache = [result for result in results]
        self.assertEqual(results._cache_is_full(), True)
        self.assertEqual(len(connections['default'].queries), 5)

    def test_quotes_regression(self):
        sqs = self.sqs.auto_query(u"44°48'40''N 20°28'32''E")
        # Should not have empty terms.
        self.assertEqual(sqs.query.build_query(), u"44\xb048'40''N 20\xb028'32''E")
        # Should not cause Solr to 500.
        self.assertEqual(sqs.count(), 0)

        sqs = self.sqs.auto_query('blazing')
        self.assertEqual(sqs.query.build_query(), u'blazing')
        self.assertEqual(sqs.count(), 0)
        sqs = self.sqs.auto_query('blazing saddles')
        self.assertEqual(sqs.query.build_query(), u'blazing saddles')
        self.assertEqual(sqs.count(), 0)
        sqs = self.sqs.auto_query('"blazing saddles')
        self.assertEqual(sqs.query.build_query(), u'\\"blazing saddles')
        self.assertEqual(sqs.count(), 0)
        sqs = self.sqs.auto_query('"blazing saddles"')
        self.assertEqual(sqs.query.build_query(), u'"blazing saddles"')
        self.assertEqual(sqs.count(), 0)
        sqs = self.sqs.auto_query('mel "blazing saddles"')
        self.assertEqual(sqs.query.build_query(), u'mel "blazing saddles"')
        self.assertEqual(sqs.count(), 0)
        sqs = self.sqs.auto_query('mel "blazing \'saddles"')
        self.assertEqual(sqs.query.build_query(), u'mel "blazing \'saddles"')
        self.assertEqual(sqs.count(), 0)
        sqs = self.sqs.auto_query('mel "blazing \'\'saddles"')
        self.assertEqual(sqs.query.build_query(), u'mel "blazing \'\'saddles"')
        self.assertEqual(sqs.count(), 0)
        sqs = self.sqs.auto_query('mel "blazing \'\'saddles"\'')
        self.assertEqual(sqs.query.build_query(), u'mel "blazing \'\'saddles" \'')
        self.assertEqual(sqs.count(), 0)
        sqs = self.sqs.auto_query('mel "blazing \'\'saddles"\'"')
        self.assertEqual(sqs.query.build_query(), u'mel "blazing \'\'saddles" \'\\"')
        self.assertEqual(sqs.count(), 0)
        sqs = self.sqs.auto_query('"blazing saddles" mel')
        self.assertEqual(sqs.query.build_query(), u'"blazing saddles" mel')
        self.assertEqual(sqs.count(), 0)
        sqs = self.sqs.auto_query('"blazing saddles" mel brooks')
        self.assertEqual(sqs.query.build_query(), u'"blazing saddles" mel brooks')
        self.assertEqual(sqs.count(), 0)
        sqs = self.sqs.auto_query('mel "blazing saddles" brooks')
        self.assertEqual(sqs.query.build_query(), u'mel "blazing saddles" brooks')
        self.assertEqual(sqs.count(), 0)
        sqs = self.sqs.auto_query('mel "blazing saddles" "brooks')
        self.assertEqual(sqs.query.build_query(), u'mel "blazing saddles" \\"brooks')
        self.assertEqual(sqs.count(), 0)

    def test_result_class(self):
        # Assert that we're defaulting to ``SearchResult``.
        sqs = self.sqs.all()
        self.assertTrue(isinstance(sqs[0], SearchResult))

        # Custom class.
        sqs = self.sqs.result_class(MockSearchResult).all()
        self.assertTrue(isinstance(sqs[0], MockSearchResult))

        # Reset to default.
        sqs = self.sqs.result_class(None).all()
        self.assertTrue(isinstance(sqs[0], SearchResult))


class LiveSolrMoreLikeThisTestCase(TestCase):
    fixtures = ['bulk_data.json']

    def setUp(self):
        super(LiveSolrMoreLikeThisTestCase, self).setUp()

        # Wipe it clean.
        clear_solr_index()

        self.old_ui = connections['default'].get_unified_index()
        self.ui = UnifiedIndex()
        self.smmi = SolrMockModelSearchIndex()
        self.sammi = SolrAnotherMockModelSearchIndex()
        self.ui.build(indexes=[self.smmi, self.sammi])
        connections['default']._index = self.ui

        self.sqs = SearchQuerySet()

        self.smmi.update()
        self.sammi.update()


    def tearDown(self):
        # Restore.
        connections['default']._index = self.old_ui
        super(LiveSolrMoreLikeThisTestCase, self).tearDown()

    def test_more_like_this(self):
        mlt = self.sqs.more_like_this(MockModel.objects.get(pk=1))
        self.assertEqual(mlt.count(), 24)
        self.assertEqual(sorted([result.pk for result in mlt]),
                         sorted(['6', '14', '4', '10', '22', '5', '3', '12',
                                 '2', '23', '18', '19', '13', '7', '15', '21',
                                 '9', '1', '2', '20', '16', '17', '8', '11']))
        self.assertEqual(len([result.pk for result in mlt]), 24)

        alt_mlt = self.sqs.filter(name='daniel3').more_like_this(MockModel.objects.get(pk=3))
        self.assertEqual(alt_mlt.count(), 10)
        self.assertEqual(sorted([result.pk for result in alt_mlt]),
                         sorted(['23', '13', '17', '16', '22', '19', '4', '10',
                                 '1', '2']))
        self.assertEqual(len([result.pk for result in alt_mlt]), 10)

        alt_mlt_with_models = self.sqs.models(MockModel).more_like_this(MockModel.objects.get(pk=1))
        self.assertEqual(alt_mlt_with_models.count(), 22)
        self.assertEqual(sorted([result.pk for result in alt_mlt_with_models]),
                         sorted(['6', '14', '4', '10', '22', '5', '3', '12',
                                 '2', '23', '18', '19', '13', '7', '15', '21',
                                 '9', '20', '16', '17', '8', '11']))
        self.assertEqual(len([result.pk for result in alt_mlt_with_models]), 22)

        if hasattr(MockModel.objects, 'defer'):
            # Make sure MLT works with deferred bits.
            mi = MockModel.objects.defer('foo').get(pk=1)
            self.assertEqual(mi._deferred, True)
            deferred = self.sqs.models(MockModel).more_like_this(mi)
            self.assertEqual(deferred.count(), 0)
            self.assertEqual([result.pk for result in deferred], [])
            self.assertEqual(len([result.pk for result in deferred]), 0)

        # Ensure that swapping the ``result_class`` works.
        self.assertTrue(isinstance(self.sqs.result_class(MockSearchResult).more_like_this(MockModel.objects.get(pk=1))[0], MockSearchResult))


class LiveSolrAutocompleteTestCase(TestCase):
    fixtures = ['bulk_data.json']

    def setUp(self):
        super(LiveSolrAutocompleteTestCase, self).setUp()

        # Wipe it clean.
        clear_solr_index()

        # Stow.
        self.old_ui = connections['default'].get_unified_index()
        self.ui = UnifiedIndex()
        self.smmi = SolrAutocompleteMockModelSearchIndex()
        self.ui.build(indexes=[self.smmi])
        connections['default']._index = self.ui

        self.sqs = SearchQuerySet()

        self.smmi.update()

    def tearDown(self):
        # Restore.
        connections['default']._index = self.old_ui
        super(LiveSolrAutocompleteTestCase, self).tearDown()

    def test_autocomplete(self):
        autocomplete = self.sqs.autocomplete(text_auto='mod')
        self.assertEqual(autocomplete.count(), 5)
        self.assertEqual([result.pk for result in autocomplete], ['1', '12', '6', '7', '14'])
        self.assertTrue('mod' in autocomplete[0].text.lower())
        self.assertTrue('mod' in autocomplete[1].text.lower())
        self.assertTrue('mod' in autocomplete[2].text.lower())
        self.assertTrue('mod' in autocomplete[3].text.lower())
        self.assertTrue('mod' in autocomplete[4].text.lower())
        self.assertEqual(len([result.pk for result in autocomplete]), 5)

        # Test multiple words.
        autocomplete_2 = self.sqs.autocomplete(text_auto='your mod')
        self.assertEqual(autocomplete_2.count(), 3)
        self.assertEqual([result.pk for result in autocomplete_2], ['1', '14', '6'])
        self.assertTrue('your' in autocomplete_2[0].text.lower())
        self.assertTrue('mod' in autocomplete_2[0].text.lower())
        self.assertTrue('your' in autocomplete_2[1].text.lower())
        self.assertTrue('mod' in autocomplete_2[1].text.lower())
        self.assertTrue('your' in autocomplete_2[2].text.lower())
        self.assertTrue('mod' in autocomplete_2[2].text.lower())
        self.assertEqual(len([result.pk for result in autocomplete_2]), 3)

        # Test multiple fields.
        autocomplete_3 = self.sqs.autocomplete(text_auto='Django', name_auto='dan')
        self.assertEqual(autocomplete_3.count(), 4)
        self.assertEqual([result.pk for result in autocomplete_3], ['12', '1', '14', '22'])
        self.assertEqual(len([result.pk for result in autocomplete_3]), 4)


class LiveSolrRoundTripTestCase(TestCase):
    def setUp(self):
        super(LiveSolrRoundTripTestCase, self).setUp()

        # Wipe it clean.
        clear_solr_index()

        # Stow.
        self.old_ui = connections['default'].get_unified_index()
        self.ui = UnifiedIndex()
        self.srtsi = SolrRoundTripSearchIndex()
        self.ui.build(indexes=[self.srtsi])
        connections['default']._index = self.ui
        self.sb = connections['default'].get_backend()

        self.sqs = SearchQuerySet()

        # Fake indexing.
        mock = MockModel()
        mock.id = 1
        self.sb.update(self.srtsi, [mock])

    def tearDown(self):
        # Restore.
        connections['default']._index = self.old_ui
        super(LiveSolrRoundTripTestCase, self).tearDown()

    def test_round_trip(self):
        results = self.sqs.filter(id='core.mockmodel.1')

        # Sanity check.
        self.assertEqual(results.count(), 1)

        # Check the individual fields.
        result = results[0]
        self.assertEqual(result.id, 'core.mockmodel.1')
        self.assertEqual(result.text, 'This is some example text.')
        self.assertEqual(result.name, 'Mister Pants')
        self.assertEqual(result.is_active, True)
        self.assertEqual(result.post_count, 25)
        self.assertEqual(result.average_rating, 3.6)
        self.assertEqual(result.price, u'24.99')
        self.assertEqual(result.pub_date, datetime.date(2009, 11, 21))
        self.assertEqual(result.created, datetime.datetime(2009, 11, 21, 21, 31, 00))
        self.assertEqual(result.tags, ['staff', 'outdoor', 'activist', 'scientist'])
        self.assertEqual(result.sites, [3, 5, 1])


if test_pickling:
    class LiveSolrPickleTestCase(TestCase):
        fixtures = ['bulk_data.json']

        def setUp(self):
            super(LiveSolrPickleTestCase, self).setUp()

            # Wipe it clean.
            clear_solr_index()

            # Stow.
            self.old_ui = connections['default'].get_unified_index()
            self.ui = UnifiedIndex()
            self.smmi = SolrMockModelSearchIndex()
            self.sammi = SolrAnotherMockModelSearchIndex()
            self.ui.build(indexes=[self.smmi, self.sammi])
            connections['default']._index = self.ui

            self.sqs = SearchQuerySet()

            self.smmi.update()
            self.sammi.update()

        def tearDown(self):
            # Restore.
            connections['default']._index = self.old_ui
            super(LiveSolrPickleTestCase, self).tearDown()

        def test_pickling(self):
            results = self.sqs.all()

            for res in results:
                # Make sure the cache is full.
                pass

            in_a_pickle = pickle.dumps(results)
            like_a_cuke = pickle.loads(in_a_pickle)
            self.assertEqual(len(like_a_cuke), len(results))
            self.assertEqual(like_a_cuke[0].id, results[0].id)


class SolrBoostBackendTestCase(TestCase):
    def setUp(self):
        super(SolrBoostBackendTestCase, self).setUp()

        # Wipe it clean.
        self.raw_solr = pysolr.Solr(settings.HAYSTACK_CONNECTIONS['default']['URL'])
        clear_solr_index()

        # Stow.
        self.old_ui = connections['default'].get_unified_index()
        self.ui = UnifiedIndex()
        self.smmi = SolrBoostMockSearchIndex()
        self.ui.build(indexes=[self.smmi])
        connections['default']._index = self.ui
        self.sb = connections['default'].get_backend()

        self.sample_objs = []

        for i in xrange(1, 5):
            mock = AFourthMockModel()
            mock.id = i

            if i % 2:
                mock.author = 'daniel'
                mock.editor = 'david'
            else:
                mock.author = 'david'
                mock.editor = 'daniel'

            mock.pub_date = datetime.date(2009, 2, 25) - datetime.timedelta(days=i)
            self.sample_objs.append(mock)

    def tearDown(self):
        connections['default']._index = self.old_ui
        super(SolrBoostBackendTestCase, self).tearDown()

    def test_boost(self):
        self.sb.update(self.smmi, self.sample_objs)
        self.assertEqual(self.raw_solr.search('*:*').hits, 4)

        results = SearchQuerySet().filter(SQ(author='daniel') | SQ(editor='daniel'))

        self.assertEqual([result.id for result in results], [
            'core.afourthmockmodel.1',
            'core.afourthmockmodel.3',
            'core.afourthmockmodel.2',
            'core.afourthmockmodel.4'
        ])


class LiveSolrContentExtractionTestCase(TestCase):
    def setUp(self):
        super(LiveSolrContentExtractionTestCase, self).setUp()

        self.sb = connections['default'].get_backend()

    def test_content_extraction(self):
        f = open(os.path.join(os.path.dirname(__file__),
                              "..", "..", "content_extraction", "test.pdf"),
                 "rb")

        data = self.sb.extract_file_contents(f)

        self.assertTrue("haystack" in data['contents'])
        self.assertEqual(data['metadata']['Content-Type'], [u'application/pdf'])
        self.assertTrue(any(i for i in data['metadata']['Keywords'] if 'SolrCell' in i))
