from flask import Blueprint, jsonify, request
from models import Billing
from decimal import Decimal
import json
from extensions import elasticsearch as es
import flask_excel as excel
from flask_cors import CORS, cross_origin



app_bp = Blueprint('app_bp', __name__, url_prefix='')

# Assumption: objectId is download_id
# Parses the elasticSearch response and makes it as similar as possible to the ICGC Data
# Portal. String "DUMMY" is used when no data for that field is available.
def parse_ES_response(es_dict, the_size, the_from, the_sort, the_order):
	protoDict = {'hits':[]}
	for hit in es_dict['hits']['hits']:
		if '_source' in hit:
			protoDict['hits'].append({
			'id' : 'DUMMY',
			'objectID' : 'DUMMY',
			'access' : 'DUMMY',
			'center_name': hit['_source']['center_name'],
			'study' : ['DUMMY'],
			'dataCategorization' : {
				'dataType' : hit['_source']['analysis_type'],
				'experimentalStrategy' : hit['_source']['workflow']
			},
			'fileCopies' : [{
				'repoDataBundleId' : 'DUMMY',
				'repoDataSetIds' :[],
				'repoCode' : 'DUMMY',
				'repoOrg' : 'DUMMY',
				'repoName' : 'DUMMY',
				'repoType' : 'DUMMY',
				'repoCountry' : 'DUMMY',
				'repoBaseUrl' : 'DUMMY',
				'repoDataPath' : 'DUMMY',
				'repoMetadatapath' : 'DUMMY',
				'indexFile' : {
					'id' : 'DUMMY',
					'objectId' : hit['_source']['download_id'],
					'fileName' : hit['_source']['title'],
					'fileFormat' : hit['_source']['file_type'],
					'fileMd5sum' : 'DUMMY',
					'fileSize' : 'DUMMY'
				},
				'fileName' : hit['_source']['title'],
				'fileFormat' : hit['_source']['file_type'],
				'fileMd5sum' : 'DUMMY',
				'lastModified' : 'DUMMY'
			}],
			'donors' : [{
				'donorId' : hit['_source']['donor'],
				'primarySite' : 'DUMMY',
				'projectCode' : hit['_source']['project'],
				'study' : 'DUMMY',
				'sampleId' : ['DUMMY'],
				'specimenType' : [hit['_source']['specimen_type']],
				'submittedDonorId' : "DUMMY",
				'submittedSampleId' : ['DUMMY'],
				'submittedSpecimenId' : ['DUMMY'],
				'otherIdentifiers' : {
					'tcgaSampleBarcode' : ['DUMMY'],
					'tcgaAliquotBarcode' : ['DUMMY']
				}

			}],

			'analysisMethod' : {
				'analysisType' : hit['_source']['analysis_type'],
				'software' : 'DUMMY'
			},
			'referenceGenome' : {
				'genomeBuild' : 'DUMMY',
				'referenceName' : 'DUMMY',
				'downloadUrl' : 'DUMMY'
			}
		})

		else:
			try:
				protoDict['hits'].append(hit['fields'])
			except:
				pass

	protoDict['pagination'] = {
		'count' : len(es_dict['hits']['hits']),#25,
		'total' : es_dict['hits']['total'],
		'size' : the_size,
		'from' : the_from+1,
		'page' : (the_from/(the_size))+1, #(the_from/(the_size+1))+1
		'pages' : -(-es_dict['hits']['total'] // the_size),
		'sort' : the_sort,
		'order' : the_order
	}

	protoDict['termFacets'] = {}#es_dict['aggregations']
	for x, y in es_dict['aggregations'].items():
		protoDict['termFacets'][x] = {'type':'terms', 'terms': map(lambda x:{"term":x["key"], 'count':x['doc_count']}, y['buckets'])}

	#Get the total for all the terms
	for section in protoDict['termFacets']:
		m_sum = 0
		#print section
		for term in protoDict['termFacets'][section]['terms']:
			m_sum += term['count']
		protoDict['termFacets'][section]['total'] = m_sum


	return protoDict

#This returns the agreggate terms and the list of hits from ElasticSearch
@app_bp.route('/files/')
@cross_origin()
def get_data():
	print "I hate my life"
	#Get all the parameters from the URL
	m_field = request.args.get('field')
	m_filters = request.args.get('filters')
	m_From = request.args.get('from', 1, type=int)
	m_Size = request.args.get('size', 10, type=int)
	m_Sort = request.args.get('sort', 'center_name')
	m_Order = request.args.get('order', 'desc')

	#Will hold the query that will be used when calling ES
	mQuery = {}
	#Gets the index in [0 - (N-1)] form to communicate with ES
	m_From -= 1 
	try:
		m_fields_List = [x.strip() for x in m_field.split(',')]
	except:
		m_fields_List = [] #Changed it from None to an empty list
	#Get a list of all the Filters requested
	try:
		m_filters = ast.literal_eval(m_filters)
		#Functions for calling the appropriates query filters
		matchValues = lambda x,y: {"filter":{"terms": {x:y['is']}}}
		filt_list = [{"constant_score": matchValues(x, y)} for x,y in m_filters['file'].items()]
		mQuery = {"bool":{"must":[filt_list]}}

	except Exception, e:
		print str(e)
		m_filters = None
		mQuery = {"match_all":{}}
		pass
	mText = es.search(index='fb_index', body={"query": mQuery, "aggs" : {
        "centerName" : {
            "terms" : { "field" : "center_name",
            			"min_doc_count" : 0,
                        "size" : 99999}           
        },
        "projectCode":{
            "terms":{
                "field" : "project",
                "min_doc_count" : 0,
                "size" : 99999
            }
        },
        "specimenType":{
            "terms":{
                "field" : "specimen_type",
                "min_doc_count" : 0,
                "size" : 99999
            }
        },
        "fileFormat":{
            "terms":{
                "field" : "file_type",
                "min_doc_count" : 0,
                "size" : 99999
            }
        },
        "workFlow":{
            "terms":{
                "field" : "workflow",
                "min_doc_count" : 0,
                "size" : 99999
            }
        },
        "analysisType":{
            "terms":{
                "field" : "analysis_type",
                "min_doc_count" : 0,
                "size" : 99999
            }
        }


    }, "_source":m_fields_List}, from_=m_From, size=m_Size, sort=m_Sort+":"+m_Order) #Changed "fields" to "_source"
	return jsonify(parse_ES_response(mText, m_Size, m_From, m_Sort, m_Order))

#Get the manifest. You need to pass on the filters
@app_bp.route('/files/export')
@cross_origin()
def get_manifest():
	m_filters = request.args.get('filters')
	m_Size = request.args.get('size', 25, type=int)
	mQuery = {}
	try:
		m_filters = ast.literal_eval(m_filters)
		#Functions for calling the appropriates query filters
		onlyOne = lambda x,y: {x:{"query": y['is'][0]}}
		moreThanOne = lambda x,y: {x:{"query": ' '.join(y['is']), "operator": "or"}}
		matchValues = lambda x,y: moreThanOne(x, y) if len(y['is']) > 1 else onlyOne(x, y)
		filt_list = [{"match": matchValues(x, y)} for x,y in m_filters['file'].items()]
		mQuery = {"bool":{"must":[filt_list]}}

	except Exception, e:
		print str(e)
		m_filters = None
		mQuery = {"match_all":{}}
		pass
	mText = es.search(index='fb_index', body={"query": mQuery}, size=m_Size)

	protoList = []
	for hit in mText['hits']['hits']:
		if '_source' in hit:
			protoList.append(hit['_source'])
	print protoList
	return excel.make_response_from_records(protoList, 'tsv', file_name = 'manifest')


#This will return a summary of the facets
@app_bp.route('/files/facets')
@cross_origin()
def get_facets():
	#Search the aggregates.
	#Parse them
	#Return it as a JSON output.
	#Things I need to know: The final format of the indexes stored in ES
	return "Test"


@app_bp.route('/invoices')
def find_invoices():
    project = str(request.args.get('project'))
    if project:
        invoices = [invoice.to_json() for invoice in Billing.query.filter(Billing.project == project).order_by(
            Billing.end_date.desc()).all()]
        return jsonify(invoices)
    else:
        return None, 401
