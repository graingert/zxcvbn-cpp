#!/usr/bin/python
import itertools
import os
import sys
import textwrap
import time
import codecs

from operator import itemgetter

def usage():
    return '''
usage:
%s data-dir frequency_lists.coffee

generates frequency_lists.coffee (zxcvbn's ranked dictionary file) from word frequency data.
data-dir should contain frequency counts, as generated by the data-scripts/count_* scripts.

DICTIONARIES controls which frequency data will be included and at maximum how many tokens
per dictionary.

If a token appears in multiple frequency lists, it will only appear once in emitted .coffee file,
in the dictionary where it has lowest rank.

Short tokens, if rare, are also filtered out. If a token has higher rank than 10**(token.length),
it will be excluded because a bruteforce match would have given it a lower guess score.

A warning will be printed if DICTIONARIES contains a dictionary name that doesn't appear in
passed data dir, or vice-versa.
    ''' % sys.argv[0]

# maps dict name to num words. None value means "include all words"
DICTIONARIES = dict(
    us_tv_and_film    = 30000,
    english_wikipedia = 30000,
    passwords         = 30000,
    surnames          = 10000,
    male_names        = None,
    female_names      = None,
)

# returns {list_name: {token: rank}}, as tokens and ranks occur in each file.
def parse_frequency_lists(data_dir):
    freq_lists = {}
    for filename in os.listdir(data_dir):
        freq_list_name, ext = os.path.splitext(filename)
        if freq_list_name not in DICTIONARIES:
            msg = 'Warning: %s appears in %s directory but not in DICTIONARY settings. Excluding.'
            print msg % (freq_list_name, data_dir)
            continue
        token_to_rank = {}
        with codecs.open(os.path.join(data_dir, filename), 'r', 'utf8') as f:
            for i, line in enumerate(f):
                rank = i + 1 # rank starts at 1
                token = line.split()[0]
                token_to_rank[token] = rank
        freq_lists[freq_list_name] = token_to_rank
    for freq_list_name in DICTIONARIES:
        if freq_list_name not in freq_lists:
            msg = 'Warning: %s appears in DICTIONARY settings but not in %s directory. Excluding.'
            print msg % (freq_list, data_dir)
    return freq_lists

def is_rare_and_short(token, rank):
    return rank >= 10**len(token)

def has_comma_or_double_quote(token, rank, lst_name):
    # hax, switch to csv or similar if this excludes too much.
    # simple comma joining has the advantage of being easy to process
    # client-side w/o needing a lib, and so far this only excludes a few
    # very high-rank tokens eg 'ps8,000' at rank 74868 from wikipedia list.
    if ',' in token or '"' in token:
        return True
    return False

def filter_frequency_lists(freq_lists):
    '''
    filters frequency data according to:
        - filter out short tokens if they are too rare.
        - filter out tokens if they already appear in another dict
          at lower rank.
        - cut off final freq_list at limits set in DICTIONARIES, if any.
    '''
    filtered_token_and_rank = {} # maps {name: [(token, rank), ...]}
    token_count = {}             # maps freq list name: current token count.
    for name in freq_lists:
        filtered_token_and_rank[name] = []
        token_count[name] = 0
    minimum_rank = {} # maps token -> lowest token rank across all freq lists
    minimum_name = {} # maps token -> freq list name with lowest token rank
    for name, token_to_rank in freq_lists.iteritems():
        for token, rank in token_to_rank.iteritems():
            if token not in minimum_rank:
                assert token not in minimum_name
                minimum_rank[token] = rank
                minimum_name[token] = name
            else:
                assert token in minimum_name
                assert minimum_name[token] != name, 'same token occurs multiple times in %s' % name
                min_rank = minimum_rank[token]
                if rank < min_rank:
                    minimum_rank[token] = rank
                    minimum_name[token] = name
    for name, token_to_rank in freq_lists.iteritems():
        for token, rank in token_to_rank.iteritems():
            if minimum_name[token] != name:
                continue
            if is_rare_and_short(token, rank) or has_comma_or_double_quote(token, rank, name):
                continue
            filtered_token_and_rank[name].append((token, rank))
            token_count[name] += 1
    result = {}
    for name, token_rank_pairs in filtered_token_and_rank.iteritems():
        token_rank_pairs.sort(key=itemgetter(1))
        cutoff_limit = DICTIONARIES[name]
        if cutoff_limit and len(token_rank_pairs) > cutoff_limit:
            token_rank_pairs = token_rank_pairs[:cutoff_limit]
        result[name] = [pair[0] for pair in token_rank_pairs] # discard rank post-sort
    return result

def to_kv(lst, lst_name):
    val = '"%s".split(",")' % ','.join(lst)
    return '%s: %s' % (lst_name, val)

def output_coffee(args, script_name, freq_lists):
    (output_file,) = args
    with codecs.open(output_file, 'w', 'utf8') as f:
        f.write('# generated by %s\n' % script_name)
        f.write('frequency_lists = \n  ')
        lines = []
        for name, lst in freq_lists.iteritems():
            lines.append(to_kv(lst, name))
        f.write('\n  '.join(lines))
        f.write('\n')
        f.write('module.exports = frequency_lists\n')

def escape(x):
    return x.replace("\\", "\\\\").replace("\"", "\\\"")

def output_hpp(output_file_hpp, script_name, freq_lists):
    # make ordered a-list
    freq_lists_alist = list(freq_lists.items())

    with codecs.open(output_file_hpp, 'w', 'utf8') as f:
        f.write('// generated by %s\n' % (script_name,))
        tags = ',\n  '.join(k.upper() for (k, _) in freq_lists_alist + [("USER_INPUTS", None)])
        f.write("""#ifndef __ZXCVBN___FREQUENCY_LISTS_HPP
#define __ZXCVBN___FREQUENCY_LISTS_HPP

#include <zxcvbn/frequency_lists_common.hpp>

#include <initializer_list>
#include <unordered_map>

namespace zxcvbn {

namespace _frequency_lists {

enum class DictionaryTag {
  %s
};

std::unordered_map<DictionaryTag, RankedDict> & get_default_ranked_dicts();

}

}

#endif"""  % (tags,))

def output_cpp(output_file_cpp, script_name, freq_lists):
    # make ordered a-list
    freq_lists_alist = list(freq_lists.items())

    with codecs.open(output_file_cpp, 'w', 'utf8') as f:
        f.write('// generated by %s\n' % (script_name,))
        f.write("#include <zxcvbn/_frequency_lists.hpp>\n")
        f.write("#include <zxcvbn/frequency_lists_common.hpp>\n")
        f.write("#include <initializer_list>\n\n")
        f.write("""namespace zxcvbn {

namespace _frequency_lists {

""")
        tw = textwrap.TextWrapper()
        tw.initial_indent = '    '
        tw.subsequent_indent = '    '
        tw.drop_whitespace = True
        tw.break_long_words = False
        tw.break_on_hyphens = False
        f.write("const char *const FREQ_LISTS[] = {\n")

        for name, lst in freq_lists_alist:
            f.write('"')
            for word in lst:
                assert len(word) <= 255
                f.write("\\%03o" % (len(word),))
                f.write(escape(word))
            f.write('",\n')
        f.write("};\n\n")

        f.write("""
class WordIterator {
  const char *_words;
    std::string _cur;


  std::string _get_cur() {
    auto len = _words[0];
    if (!len) return std::string();
    return std::string(&_words[1], &_words[1 + len]);
  }

public:
  WordIterator(const char *words) :
    _words(words), _cur(_get_cur()) {}


  std::string & operator *() {
    return _cur;
  }

  const std::string & operator *() const {
    return _cur;
  }

  WordIterator & operator++() {
    _words += 1 + _words[0];
    _cur = _get_cur();
    return *this;
  }

  bool operator!=(const WordIterator & rhs) const {
    return rhs._words != _words;
  }
};

class WordIterable {
  const char *_words;
  const std::size_t _len;

public:
  WordIterable(const char *words, std::size_t len)
    : _words(words), _len(len) {}

  WordIterator begin() const {
    return WordIterator(_words);
  }

  WordIterator end() const {
    return WordIterator(_words + _len);
  }
};

static
std::unordered_map<DictionaryTag, RankedDict> build_static_ranked_dicts() {
  std::unordered_map<DictionaryTag, RankedDict> toret;
  std::underlying_type_t<DictionaryTag> tag_idx = 0;
  for (const auto & strs : FREQ_LISTS) {
    toret.insert(std::make_pair(static_cast<DictionaryTag>(tag_idx),
                                build_ranked_dict(WordIterable(strs, std::strlen(strs)))));
    tag_idx += 1;
  }
  return toret;
}

static auto _ranked_dicts = build_static_ranked_dicts();

std::unordered_map<DictionaryTag, RankedDict> & get_default_ranked_dicts() {
  return _ranked_dicts;
}

""")
        f.write("}\n\n}\n")

def main():
    if len(sys.argv) != 3:
        print usage()
        sys.exit(0)
    data_dir, output_file = sys.argv[1:]
    unfiltered_freq_lists = parse_frequency_lists(data_dir)
    freq_lists = filter_frequency_lists(unfiltered_freq_lists)

    _, ext = os.path.splitext(output_file.lower())
    if ext == ".cpp":
        output_fn = output_cpp
    elif ext == ".hpp":
        output_fn = output_hpp
    else:
        output_fn = output_coffee

    script_name = os.path.split(sys.argv[0])[1]
    output_fn(output_file, script_name, freq_lists)

if __name__ == '__main__':
    main()
