$(document).ready(function () {
'use strict';

    _($("select.o_specific_answer,select.o_general_answer")).each(function(elem) {
        $(elem).select2({ minimumResultsForSearch: -1, width: '100%' });
    });

});